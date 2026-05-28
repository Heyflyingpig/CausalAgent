import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from langchain_community.document_loaders import PyPDFLoader
from langchain_openai import ChatOpenAI
from ragas.embeddings.base import LangchainEmbeddingsWrapper
from ragas.llms.base import LangchainLLMWrapper
from ragas.run_config import RunConfig
from ragas.testset import TestsetGenerator

from config.settings import settings
from Agent.knowledge_base.rag.query_rag import _get_embedding_function
from Agent.knowledge_base.rag.operation_datasets.dataset_utils import (
    append_samples_to_auto_dataset,
    convert_ragas_generated_row_to_eval_sample,
    validate_all_datasets,
    write_dataset_validation_outputs,
)


RAG_DIR = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE_DIR = RAG_DIR.parent
SOURCE_DIR = KNOWLEDGE_BASE_DIR / "source"
OUTPUT_DIR = RAG_DIR / "output"
MACHINE_OUTPUT_DIR = OUTPUT_DIR / "machine"
DEFAULT_RAW_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "ragas_generated_testset.json"
DEFAULT_CONVERTED_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "ragas_generated_eval_samples.json"

# 本地手动运行时优先改这里。
# append_to_auto=True 会把转换后的样本直接追加到 data/rag_eval_auto.json。
# 首次建议 testset_size=10，确认质量后再提高到 20 或 50。
RAGAS_TESTSET_GENERATE_CONFIG = {
    "source_dir": str(SOURCE_DIR),
    "raw_output_path": str(DEFAULT_RAW_OUTPUT_PATH),
    "converted_output_path": str(DEFAULT_CONVERTED_OUTPUT_PATH),
    "testset_size": 10,
    "max_pages_per_pdf": 80,
    "append_to_auto": True,
    "save_machine_output": True,
    "run_config_timeout": 1200,
    "run_config_max_workers": 2,
    "print_full_output": False,
}


def _ensure_parent_dir(path: Path) -> None:
    """确保输出文件所在目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, data: Any) -> None:
    """写入 JSON 文件。"""
    _ensure_parent_dir(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_source_documents(source_dir: Path, max_pages_per_pdf: int | None) -> List[Any]:
    """从 source 目录读取 PDF 文档页，供 Ragas testset generation 使用。"""
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


def _build_generator() -> TestsetGenerator:
    """构造 Ragas TestsetGenerator。"""
    llm = ChatOpenAI(
        api_key=settings.API_KEY,
        base_url=settings.BASE_URL,
        model_name=settings.MODEL,
        temperature=0,
    )
    return TestsetGenerator.from_langchain(
        llm=LangchainLLMWrapper(llm),
        embedding_model=LangchainEmbeddingsWrapper(_get_embedding_function()),
    )


def _generate_raw_testset(documents: List[Any]) -> List[Dict[str, Any]]:
    """调用 Ragas 生成原始 testset，并转成 list[dict]。"""
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
    """运行 Ragas testset generation，并可选择直接追加到 auto 数据集。"""
    started_at = time.perf_counter()
    documents = _load_source_documents(
        Path(RAGAS_TESTSET_GENERATE_CONFIG["source_dir"]),
        RAGAS_TESTSET_GENERATE_CONFIG.get("max_pages_per_pdf"),
    )
    raw_rows = _generate_raw_testset(documents)
    converted_samples = _convert_raw_rows(raw_rows)

    append_result = None
    if RAGAS_TESTSET_GENERATE_CONFIG.get("append_to_auto"):
        append_result = append_samples_to_auto_dataset(converted_samples)
        validation_result = validate_all_datasets()
        write_dataset_validation_outputs(validation_result)
    else:
        validation_result = None

    if RAGAS_TESTSET_GENERATE_CONFIG.get("save_machine_output"):
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
                "append_to_auto": RAGAS_TESTSET_GENERATE_CONFIG["append_to_auto"],
                "samples": converted_samples,
            },
        )

    return {
        "status": "pass",
        "source_document_count": len(documents),
        "generated_count": len(raw_rows),
        "converted_count": len(converted_samples),
        "append_to_auto": RAGAS_TESTSET_GENERATE_CONFIG["append_to_auto"],
        "append_result": append_result,
        "validation_status": validation_result.get("status") if validation_result else "not_run",
        "eval_seconds": round(time.perf_counter() - started_at, 3),
        "raw_output_path": str(Path(RAGAS_TESTSET_GENERATE_CONFIG["raw_output_path"]).resolve()),
        "converted_output_path": str(Path(RAGAS_TESTSET_GENERATE_CONFIG["converted_output_path"]).resolve()),
    }


if __name__ == "__main__":
    output = run_ragas_testset_generation_from_code_config()
    if RAGAS_TESTSET_GENERATE_CONFIG.get("print_full_output"):
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "status": output.get("status"),
                    "source_document_count": output.get("source_document_count"),
                    "generated_count": output.get("generated_count"),
                    "converted_count": output.get("converted_count"),
                    "append_to_auto": output.get("append_to_auto"),
                    "append_result": output.get("append_result"),
                    "validation_status": output.get("validation_status"),
                    "eval_seconds": output.get("eval_seconds"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

