import csv
import hashlib
import json
import os
from typing import Any, Dict, List, Optional

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

base_dir = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(base_dir, "models", "bge-small-zh-v1.5")
PERSIST_DIRECTORY = os.path.join(base_dir, "db")
DEFAULT_JSON_OUTPUT = os.path.join(base_dir, "exported_chunk_metadata.json")
DEFAULT_CSV_OUTPUT = os.path.join(base_dir, "exported_chunk_metadata.csv")


def _safe_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truncate_text(text: str, max_chars: int = 240) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _normalize_metadata(metadata: Optional[Dict[str, Any]], page_content: str, fallback_index: int) -> Dict[str, Any]:
    normalized = dict(metadata or {})
    source = normalized.get("source") or normalized.get("file_path") or "unknown_source"
    source_name = os.path.basename(source) if os.path.isabs(source) else source
    title = normalized.get("title") or os.path.splitext(source_name)[0]
    page = _safe_int(normalized.get("page"))
    chunk_index = _safe_int(normalized.get("chunk_index"))
    if chunk_index is None:
        chunk_index = fallback_index

    doc_id = normalized.get("doc_id") or os.path.splitext(source_name)[0].lower().replace(" ", "_")
    page_fragment = page if page is not None else "na"
    chunk_hash = hashlib.md5(page_content.encode("utf-8")).hexdigest()[:8]
    chunk_id = normalized.get("chunk_id") or f"{doc_id}#p{page_fragment}#c{chunk_index}_{chunk_hash}"
    doc_type = normalized.get("doc_type") or ("reference_pdf" if source_name.lower().endswith(".pdf") else "note")
    corpus = normalized.get("corpus") or ("test" if "test" in source_name.lower() else "official")

    return {
        "source": source,
        "source_name": source_name,
        "title": title,
        "doc_id": doc_id,
        "page": page,
        "chunk_index": chunk_index,
        "chunk_id": chunk_id,
        "doc_type": doc_type,
        "corpus": corpus,
        "section": normalized.get("section", ""),
    }


def _load_vector_store() -> Chroma:
    embedding_function = HuggingFaceEmbeddings(
        model_name=MODEL_PATH,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    return Chroma(
        persist_directory=PERSIST_DIRECTORY,
        embedding_function=embedding_function,
    )


def export_chunk_metadata(
    json_output_path: str = DEFAULT_JSON_OUTPUT,
    csv_output_path: str = DEFAULT_CSV_OUTPUT,
) -> Dict[str, Any]:
    """
    导出当前向量库中的 chunk metadata，便于人工标注 gold_chunk_ids。

    输出内容包含：
    - chunk_id
    - doc_id
    - source/source_name/title
    - page/chunk_index/doc_type/corpus/section
    - content_preview
    """
    db = _load_vector_store()
    raw = db.get(include=["documents", "metadatas"])
    documents = raw.get("documents", [])
    metadatas = raw.get("metadatas", [])

    rows: List[Dict[str, Any]] = []
    for index, page_content in enumerate(documents):
        metadata = _normalize_metadata(
            metadatas[index] if index < len(metadatas) else {},
            page_content,
            fallback_index=index,
        )
        rows.append(
            {
                "row_index": index,
                "chunk_id": metadata["chunk_id"],
                "doc_id": metadata["doc_id"],
                "title": metadata["title"],
                "source_name": metadata["source_name"],
                "source": metadata["source"],
                "page": metadata["page"],
                "chunk_index": metadata["chunk_index"],
                "doc_type": metadata["doc_type"],
                "corpus": metadata["corpus"],
                "section": metadata["section"],
                "content_preview": _truncate_text(page_content),
            }
        )

    with open(json_output_path, "w", encoding="utf-8") as json_file:
        json.dump(rows, json_file, ensure_ascii=False, indent=2)

    fieldnames = [
        "row_index",
        "chunk_id",
        "doc_id",
        "title",
        "source_name",
        "source",
        "page",
        "chunk_index",
        "doc_type",
        "corpus",
        "section",
        "content_preview",
    ]
    with open(csv_output_path, "w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "count": len(rows),
        "json_output_path": json_output_path,
        "csv_output_path": csv_output_path,
    }


if __name__ == "__main__":
    result = export_chunk_metadata()
    print(json.dumps(result, ensure_ascii=False, indent=2))
