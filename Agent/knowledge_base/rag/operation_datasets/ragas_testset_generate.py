import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def _load_project_dotenv_override() -> None:
    """让本脚本优先使用项目根目录 .env，避免旧终端环境变量覆盖 RAG 测试配置。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    env_path = Path(__file__).resolve().parents[4] / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)


_load_project_dotenv_override()

from Agent.knowledge_base.rag.rag_config import RAGAS_TESTSET_GENERATE_CONFIG
from Agent.knowledge_base.rag.operation_datasets.dataset_utils import (
    convert_ragas_generated_row_to_eval_sample,
    validate_all_datasets,
    write_generated_eval_dataset,
    write_dataset_validation_outputs,
)


RAG_DIR = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE_DIR = RAG_DIR.parent
SOURCE_DIR = KNOWLEDGE_BASE_DIR / "source"
OUTPUT_DIR = RAG_DIR / "output"
MACHINE_OUTPUT_DIR = OUTPUT_DIR / "machine"
DEFAULT_RAW_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "ragas_generated_testset.json"
DEFAULT_CONVERTED_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "ragas_generated_eval_samples.json"

# 本地手动运行时优先改 Agent/knowledge_base/rag/rag_config.py 里的
# RAGAS_TESTSET_GENERATE_CONFIG。


def _ensure_parent_dir(path: Path) -> None:
    """确保输出文件所在目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, data: Any) -> None:
    """写入 JSON 文件。"""
    _ensure_parent_dir(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_local_embedding_model(model_path: Path) -> None:
    """确认本地 embedding 模型目录包含 transformers 可加载的权重文件。"""
    required_any = ["model.safetensors", "pytorch_model.bin", "tf_model.h5", "model.ckpt.index", "flax_model.msgpack"]
    tokenizer_any = ["tokenizer.json", "vocab.txt", "sentencepiece.bpe.model"]
    recommended_files = ["config.json", "modules.json", "sentence_bert_config.json", "1_Pooling/config.json"]
    download_cache = model_path / ".cache" / "huggingface" / "download"
    if not model_path.exists():
        raise FileNotFoundError(f"Embedding model directory does not exist: {model_path}")
    missing_groups = []
    if not any((model_path / filename).exists() for filename in required_any):
        missing_groups.append(f"one weight file from {required_any}")
    if not any((model_path / filename).exists() for filename in tokenizer_any):
        missing_groups.append(f"one tokenizer file from {tokenizer_any}")
    missing_recommended = [filename for filename in recommended_files if not (model_path / filename).exists()]
    if missing_recommended:
        missing_groups.append(f"metadata files {missing_recommended}")
    if missing_groups:
        found_files = sorted(path.name for path in model_path.iterdir())
        cache_metadata_files = sorted(path.name for path in download_cache.glob("*.metadata")) if download_cache.exists() else []
        raise FileNotFoundError(
            "Embedding model directory is incomplete. "
            f"Missing: {missing_groups}. "
            f"Model root: {model_path}. "
            f"Current root files: {found_files}. "
            f"Cache metadata files do not contain actual model content: {cache_metadata_files}. "
            "Please download the full bge-small-zh-v1.5 sentence-transformers snapshot."
        )


def run_preflight_check() -> Dict[str, Any]:
    """检查 Ragas 生成测试集所需的本地资源，不调用外部 LLM。"""
    source_dir = Path(RAGAS_TESTSET_GENERATE_CONFIG["source_dir"])
    model_path = Path(RAGAS_TESTSET_GENERATE_CONFIG["embedding_model_path"])
    pdf_files = sorted(source_dir.glob("*.pdf"))
    _validate_local_embedding_model(model_path)
    if not pdf_files:
        raise FileNotFoundError(f"No PDF documents found in {source_dir}")
    return {
        "status": "pass",
        "source_dir": str(source_dir.resolve()),
        "source_pdf_count": len(pdf_files),
        "source_pdfs": [path.name for path in pdf_files],
        "embedding_model_path": str(model_path.resolve()),
        "embedding_device": RAGAS_TESTSET_GENERATE_CONFIG.get("embedding_device", "cpu"),
        "eval_dataset_path": str(Path(RAGAS_TESTSET_GENERATE_CONFIG["eval_dataset_path"]).resolve()),
    }


def _build_embedding_model() -> Any:
    """构造 Ragas testset generation 使用的 embedding wrapper。"""
    from langchain_huggingface import HuggingFaceEmbeddings
    from ragas.embeddings.base import LangchainEmbeddingsWrapper

    model_path = Path(RAGAS_TESTSET_GENERATE_CONFIG["embedding_model_path"])
    _validate_local_embedding_model(model_path)
    embeddings = HuggingFaceEmbeddings(
        model_name=str(model_path),
        model_kwargs={"device": RAGAS_TESTSET_GENERATE_CONFIG.get("embedding_device", "cpu")},
        encode_kwargs={"normalize_embeddings": True},
    )
    return LangchainEmbeddingsWrapper(embeddings)


def _load_source_documents(source_dir: Path, max_pages_per_pdf: int | None) -> List[Any]:
    """从 source 目录读取 PDF 文档页，供 Ragas testset generation 使用。"""
    from langchain_community.document_loaders import PyPDFLoader

    documents = []
    for pdf_path in sorted(source_dir.glob("*.pdf")):
        loaded = PyPDFLoader(str(pdf_path)).load()
        if max_pages_per_pdf is not None:
            loaded = loaded[:max_pages_per_pdf]
        for doc in loaded:
            doc.metadata["source_name"] = pdf_path.name
        documents.extend(loaded)
    if not documents:
        raise FileNotFoundError(f"No PDF documents found in {source_dir}")
    return documents


def _build_openai_client() -> Any:
    """构造 OpenAI-compatible client，供 Ragas testset generation 调用。"""
    from openai import OpenAI

    from config.settings import settings

    return OpenAI(
        api_key=settings.API_KEY,
        base_url=settings.BASE_URL,
    )


def _run_llm_preflight() -> Dict[str, Any]:
    """用一次极小请求提前验证 judge/generator LLM 是否可用。"""
    from config.settings import settings

    client = _build_openai_client()
    response = client.chat.completions.create(
        model=settings.MODEL,
        messages=[{"role": "user", "content": "Reply with OK."}],
        temperature=0,
        max_tokens=4,
    )
    return {
        "status": "pass",
        "model": settings.MODEL,
        "base_url": settings.BASE_URL,
        "response": response.choices[0].message.content,
    }


def _build_generator() -> Any:
    """构造 Ragas TestsetGenerator。"""
    from ragas.llms import llm_factory
    from ragas.testset import TestsetGenerator

    from config.settings import settings

    client = _build_openai_client()
    llm = llm_factory(
        settings.MODEL,
        provider="openai",
        client=client,
        temperature=0,
    )
    return TestsetGenerator(
        llm=llm,
        embedding_model=_build_embedding_model(),
    )


def _generate_raw_testset(documents: List[Any]) -> List[Dict[str, Any]]:
    """调用 Ragas 生成原始 testset，并转成 list[dict]。"""
    from ragas.run_config import RunConfig

    generator = _build_generator()
    testset = generator.generate_with_langchain_docs(
        documents=documents,
        testset_size=int(RAGAS_TESTSET_GENERATE_CONFIG["testset_size"]),
        run_config=RunConfig(
            timeout=int(RAGAS_TESTSET_GENERATE_CONFIG["run_config_timeout"]),
            max_workers=int(RAGAS_TESTSET_GENERATE_CONFIG["run_config_max_workers"]),
        ),
    )
    return testset.to_list()


def _convert_raw_rows(raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把 Ragas 原始样本转换成当前 eval sample schema。"""
    converted = []
    for row in raw_rows:
        converted.append(convert_ragas_generated_row_to_eval_sample(row))
    return converted


def run_ragas_testset_generation_from_code_config() -> Dict[str, Any]:
    """调用 Ragas TestsetGenerator 从 source PDF 自动生成当前 RAG eval 测试集。"""
    started_at = time.perf_counter()
    preflight = run_preflight_check()
    if RAGAS_TESTSET_GENERATE_CONFIG.get("mode") == "preflight":
        preflight["eval_seconds"] = round(time.perf_counter() - started_at, 3)
        return preflight

    llm_preflight = None
    if RAGAS_TESTSET_GENERATE_CONFIG.get("llm_preflight_enabled", True):
        llm_preflight = _run_llm_preflight()

    documents = _load_source_documents(
        Path(RAGAS_TESTSET_GENERATE_CONFIG["source_dir"]),
        RAGAS_TESTSET_GENERATE_CONFIG.get("max_pages_per_pdf"),
    )
    raw_rows = _generate_raw_testset(documents)
    converted_samples = _convert_raw_rows(raw_rows)

    write_result = None
    if RAGAS_TESTSET_GENERATE_CONFIG.get("write_eval_dataset"):
        write_result = write_generated_eval_dataset(
            converted_samples,
            dataset_path=Path(RAGAS_TESTSET_GENERATE_CONFIG["eval_dataset_path"]),
            merge_existing=True,
        )
        validation_result = validate_all_datasets()
        write_dataset_validation_outputs(validation_result)
    else:
        validation_result = None

    if RAGAS_TESTSET_GENERATE_CONFIG.get("save_machine_output"):
        from config.settings import settings

        _write_json(
            Path(RAGAS_TESTSET_GENERATE_CONFIG["raw_output_path"]),
            {
                "generator": "ragas",
                "testset_size": RAGAS_TESTSET_GENERATE_CONFIG["testset_size"],
                "model": settings.MODEL,
                "source_dir": str(Path(RAGAS_TESTSET_GENERATE_CONFIG["source_dir"]).resolve()),
                "raw_rows": raw_rows,
            },
        )
        _write_json(
            Path(RAGAS_TESTSET_GENERATE_CONFIG["converted_output_path"]),
            {
                "sample_count": len(converted_samples),
                "write_eval_dataset": RAGAS_TESTSET_GENERATE_CONFIG["write_eval_dataset"],
                "eval_dataset_path": RAGAS_TESTSET_GENERATE_CONFIG["eval_dataset_path"],
                "samples": converted_samples,
            },
        )

    return {
        "status": "pass",
        "preflight": preflight,
        "llm_preflight": llm_preflight,
        "source_document_count": len(documents),
        "generated_count": len(raw_rows),
        "converted_count": len(converted_samples),
        "write_eval_dataset": RAGAS_TESTSET_GENERATE_CONFIG["write_eval_dataset"],
        "write_result": write_result,
        "validation_status": validation_result.get("status") if validation_result else "not_run",
        "eval_seconds": round(time.perf_counter() - started_at, 3),
        "raw_output_path": str(Path(RAGAS_TESTSET_GENERATE_CONFIG["raw_output_path"]).resolve()),
        "converted_output_path": str(Path(RAGAS_TESTSET_GENERATE_CONFIG["converted_output_path"]).resolve()),
        "eval_dataset_path": str(Path(RAGAS_TESTSET_GENERATE_CONFIG["eval_dataset_path"]).resolve()),
    }


if __name__ == "__main__":
    try:
        output = run_ragas_testset_generation_from_code_config()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "fail",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "source_dir": RAGAS_TESTSET_GENERATE_CONFIG.get("source_dir"),
                    "embedding_model_path": RAGAS_TESTSET_GENERATE_CONFIG.get("embedding_model_path"),
                    "eval_dataset_path": RAGAS_TESTSET_GENERATE_CONFIG.get("eval_dataset_path"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)

    if RAGAS_TESTSET_GENERATE_CONFIG.get("print_full_output"):
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif RAGAS_TESTSET_GENERATE_CONFIG.get("mode") == "preflight":
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "status": output.get("status"),
                    "source_document_count": output.get("source_document_count"),
                    "generated_count": output.get("generated_count"),
                    "converted_count": output.get("converted_count"),
                    "write_eval_dataset": output.get("write_eval_dataset"),
                    "write_result": output.get("write_result"),
                    "validation_status": output.get("validation_status"),
                    "eval_seconds": output.get("eval_seconds"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

