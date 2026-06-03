import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from Agent.knowledge_base.query_rag import RagRetrievalConfig, build_retrieval_trace
from Agent.knowledge_base.rag.rag_config import (
    ACTIVE_EVAL_DATASET_PATH,
    CANDIDATE_GENERATION_CONFIG,
    DATA_DIR,
    MACHINE_OUTPUT_DIR,
    RETRIEVAL_PROFILES,
)

RAG_DIR = Path(__file__).resolve().parents[1]
LEGACY_DATASET_PATH = RAG_DIR / "rag_eval_sample.json"
DEFAULT_DATASET_PATH = ACTIVE_EVAL_DATASET_PATH
DEFAULT_OUTPUT_PATH = MACHINE_OUTPUT_DIR / "rag_eval_candidates_top20.json"

# 本地手动运行时优先改这里；不传命令行参数时会直接使用这组配置。
# 例如只想先给前 5 道题生成 top-20 候选，就把 limit 设为 5。
# 默认读取 PubMedQA active benchmark；
# 旧的 rag_eval_sample.json 暂时保留为兼容入口。
CANDIDATE_RUN_CONFIG = CANDIDATE_GENERATION_CONFIG


def load_eval_dataset(dataset_path: str) -> List[Dict[str, Any]]:
    """
    加载评测数据集

    Args:
        dataset_path (str): 评测数据集文件路径

    Returns:
        List[Dict[str, Any]]: 返回评测数据列表，每个元素是一个包含评测样本的字典

    Raises:
        ValueError: 当 JSON 文件内容不是数组格式时抛出异常
    """
    path = Path(dataset_path)
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("评测数据必须是 JSON 数组。")
    return data


def _candidate_to_dict(rank: int, candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    将检索候选结果转换为字典格式

    Args:
        rank (int): 候选结果的排名位置
        candidate (Dict[str, Any]): 包含候选结果信息的字典，包含元数据和评分等信息

    Returns:
        Dict[str, Any]: 转换后的字典，包含排名、文档 ID、标题、来源、页面、分数等信息
    """
    metadata = candidate.get("metadata", {})
    return {
        "rank": rank,
        "chunk_id": metadata.get("chunk_id", ""),
        "doc_id": metadata.get("doc_id", ""),
        "title": metadata.get("title", ""),
        "source_name": metadata.get("source_name", ""),
        "page": metadata.get("page"),
        "chunk_index": metadata.get("chunk_index"),
        "corpus": metadata.get("corpus", ""),
        "doc_type": metadata.get("doc_type", ""),
        "section": metadata.get("section", ""),
        "dense_score": round(float(candidate.get("dense_score", 0.0)), 4),
        "sparse_score": round(float(candidate.get("sparse_score", 0.0)), 4),
        "rerank_score": round(float(candidate.get("rerank_score", 0.0)), 4),
        "retrieval_source": candidate.get("retrieval_source", ""),
        "content_preview": candidate.get("page_content", "")[:400],
    }


def generate_candidate_file(
    dataset_path: str = str(DEFAULT_DATASET_PATH),
    output_path: str = str(DEFAULT_OUTPUT_PATH),
    top_k: int = 20,
    limit: Optional[int] = None,
    retrieval_profile: str = "candidate_top20",
) -> Dict[str, Any]:
    """
    生成 RAG 检索候选结果文件

    该函数加载评测数据集，对每个问题执行 RAG 检索，并将检索结果保存到输出文件。

    Args:
        dataset_path (str): 评测数据集文件路径，默认为 DEFAULT_DATASET_PATH
        output_path (str): 输出文件路径，默认为 DEFAULT_OUTPUT_PATH
        top_k (int): 每个问题保留的顶级候选结果数量，默认为 20
        limit (Optional[int]): 只处理前 N 条样本；为 None 时处理全部样本

    Returns:
        Dict[str, Any]: 包含处理结果的字典，包括数据集路径、输出路径、top_k 值、样本数量和结果列表
    """
    # 加载评测数据集，并在需要时只截取前若干条样本
    dataset = load_eval_dataset(dataset_path)
    if limit is not None:
        dataset = dataset[:limit]

    # 创建 RAG 检索配置，生成更宽松的 top-k 候选池，便于后续人工筛选 gold
    config_values = dict(RETRIEVAL_PROFILES[retrieval_profile])
    config_values["final_top_k"] = top_k
    config = RagRetrievalConfig(**config_values)

    results: List[Dict[str, Any]] = []
    # 遍历数据集中的每个样本，生成对应的 top-k 候选列表
    for sample in dataset:
        question = sample.get("question", "").strip()
        if not question:
            continue

        trace = build_retrieval_trace(question, config=config)
        final_candidates = trace["stages"]["final"][:top_k]
        candidate_rows = [
            _candidate_to_dict(rank=index, candidate=candidate)
            for index, candidate in enumerate(final_candidates, start=1)
        ]

        results.append(
            {
                "question": question,
                "question_type": sample.get("question_type", ""),
                "expected_corpus": sample.get("expected_corpus", ""),
                "expected_sources": sample.get("expected_sources", sample.get("gold_doc_ids", [])),
                "expected_claims": sample.get("expected_claims", []),
                "reference_answer": sample.get("reference_answer", ""),
                "gold_doc_ids": sample.get("gold_doc_ids", []),
                "gold_chunk_ids": sample.get("gold_chunk_ids", []),
                "judge_rubric": sample.get("judge_rubric", {}),
                "notes": sample.get("notes", ""),
                "config": config.to_dict(),
                "candidate_count": len(candidate_rows),
                "candidates": candidate_rows,
            }
        )

    output = {
        "dataset_path": str(Path(dataset_path).resolve()),
        "output_path": str(Path(output_path).resolve()),
        "top_k": top_k,
        "retrieval_profile": retrieval_profile,
        "sample_count": len(results),
        "results": results,
    }

    # 将候选结果写入输出文件，供后续人工标注和 benchmark 使用
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    return output

def run_candidate_generation_from_code_config() -> Dict[str, Any]:
    """
    使用文件顶部的 CANDIDATE_RUN_CONFIG 生成候选文件。

    Returns:
        Dict[str, Any]: 候选生成结果摘要与逐题候选列表。
    """
    return generate_candidate_file(
        dataset_path=CANDIDATE_RUN_CONFIG["dataset_path"],
        output_path=CANDIDATE_RUN_CONFIG["output_path"],
        top_k=CANDIDATE_RUN_CONFIG["top_k"],
        limit=CANDIDATE_RUN_CONFIG["limit"],
        retrieval_profile=CANDIDATE_RUN_CONFIG["retrieval_profile"],
    )


if __name__ == "__main__":
    result = run_candidate_generation_from_code_config()
    print(json.dumps(result, ensure_ascii=False, indent=2))



