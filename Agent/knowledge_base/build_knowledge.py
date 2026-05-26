import os
import sys
from typing import Dict, List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyMuPDFLoader, PyPDFLoader
from langchain_huggingface import HuggingFaceEmbeddings

base_dir = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(base_dir, "models", "bge-small-zh-v1.5")
SOURCE_DIRECTORY = os.path.join(base_dir, "source")
PERSIST_DIRECTORY = os.path.join(base_dir, "db")

print("正在加载本地Embedding模型...")
embedding_function = HuggingFaceEmbeddings(
    model_name=MODEL_PATH,
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)
print("Embedding模型加载完毕。")

## 转换ID，增加保留下划线
def _slugify(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.lower())
    return safe.strip("_") or "unknown_doc"


def _detect_corpus(file_name: str) -> str:
    return "test" if "test" in file_name.lower() else "official"


def _build_base_metadata(file_path: str, file_type: str) -> Dict[str, object]:
    source_name = os.path.basename(file_path)
    title = os.path.splitext(source_name)[0]
    return {
        "source": file_path,
        "source_name": source_name,
        "title": title,
        "doc_id": _slugify(title),
        "file_type": file_type,
        "doc_type": "reference_pdf" if file_type == "pdf" else "note",
        "corpus": _detect_corpus(source_name),
        "language": "zh_or_mixed",
    }


def _load_documents() -> List[Document]:
    documents: List[Document] = []
    print(f"将从以下目录加载文档: {SOURCE_DIRECTORY}")

    for root, _, files in os.walk(SOURCE_DIRECTORY):
        print(f"正在扫描文件夹: {root}")
        for file_name in files:
            file_path = os.path.join(root, file_name)
            base_metadata = _build_base_metadata(file_path, file_name.rsplit(".", 1)[-1].lower())

            if file_name.endswith(".txt"):
                try:
                    with open(file_path, "r", encoding="utf-8") as file:
                        text = file.read()
                    documents.append(Document(page_content=text, metadata=base_metadata))
                    print(f"成功加载 TXT 文件: {file_path}")
                except Exception as exc:
                    print(f"加载 TXT 文件 {file_path} 时出错: {exc}")

            elif file_name.endswith(".pdf"):
                try:
                    pdf_docs = _load_pdf_documents(file_path)
                    for page_doc in pdf_docs:
                        merged_metadata = dict(base_metadata)
                        merged_metadata.update(page_doc.metadata or {})
                        merged_metadata["source"] = file_path
                        merged_metadata["source_name"] = base_metadata["source_name"]
                        merged_metadata["title"] = merged_metadata.get("title") or base_metadata["title"]
                        merged_metadata["doc_id"] = base_metadata["doc_id"]
                        merged_metadata["file_type"] = "pdf"
                        merged_metadata["doc_type"] = "reference_pdf"
                        merged_metadata["corpus"] = base_metadata["corpus"]
                        page_doc.metadata = merged_metadata
                    documents.extend(pdf_docs)
                    print(f"成功加载 PDF 文件: {file_path} (共 {len(pdf_docs)} 页)")
                except Exception as exc:
                    print(f"加载 PDF 文件 {file_path} 时出错: {exc}")

    return documents


def _attach_chunk_metadata(split_docs: List[Document]) -> List[Document]:
    chunk_counts: Dict[str, int] = {}
    for document in split_docs:
        metadata = dict(document.metadata or {})
        doc_id = str(metadata.get("doc_id", "unknown_doc"))
        page = metadata.get("page")
        page_fragment = page if page is not None else "na"

        chunk_index = chunk_counts.get(doc_id, 0)
        chunk_counts[doc_id] = chunk_index + 1

        metadata["chunk_index"] = chunk_index
        metadata["chunk_id"] = f"{doc_id}#p{page_fragment}#c{chunk_index}"
        metadata["section"] = metadata.get("section", "")
        document.metadata = metadata

    return split_docs


def _load_pdf_documents(file_path: str) -> List[Document]:
    loader_errors: List[str] = []

    try:
        import pymupdf  # noqa: F401
    except Exception as exc:
        try:
            import fitz as pymupdf  # type: ignore

            # 兼容旧版 PyMuPDF：它暴露的是 fitz，而 LangChain 新版 loader 只导入 pymupdf。
            sys.modules["pymupdf"] = pymupdf
        except Exception as fallback_exc:
            loader_errors.append(
                f"PyMuPDFLoader 预检查失败: {exc} | fitz 回退失败: {fallback_exc}"
            )
    else:
        try:
            return PyMuPDFLoader(file_path).load()
        except Exception as exc:
            loader_errors.append(f"PyMuPDFLoader: {exc}")

    if "pymupdf" in sys.modules:
        try:
            return PyMuPDFLoader(file_path).load()
        except Exception as exc:
            loader_errors.append(f"PyMuPDFLoader: {exc}")

    try:
        return PyPDFLoader(file_path).load()
    except Exception as exc:
        loader_errors.append(f"PyPDFLoader: {exc}")

    raise RuntimeError(" | ".join(loader_errors))


def build() -> None:
    """
    构建向量知识库：加载文档 -> 标准化metadata -> 切分 -> 向量化 -> 存储。

    """
    print("开始构建向量知识库...")
    documents = _load_documents()

    if not documents:
        print("未加载到任何文档。请检查SOURCE_DIRECTORY路径及文件格式。")
        return

    print(f"成功加载 {len(documents)} 篇文档。")

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    split_docs = text_splitter.split_documents(documents)
    split_docs = _attach_chunk_metadata(split_docs)
    print(f"文档已切分为 {len(split_docs)} 个小块。")

    print("正在将文档存入向量数据库...")
    db = Chroma.from_documents(
        split_docs,
        embedding_function,
        persist_directory=PERSIST_DIRECTORY,
    )
    # 新版 langchain_chroma 在写入时会自动持久化，不再暴露 persist()；
    if hasattr(db, "persist"):
        db.persist()
    print("知识库构建完成！")



if __name__ == "__main__":
    build()
