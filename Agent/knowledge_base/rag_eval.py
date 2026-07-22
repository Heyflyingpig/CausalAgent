import json
import sys
from pathlib import Path
from typing import Any, Dict, List

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from Agent.knowledge_base.query_rag import _retrieve_candidates, get_rag_response

def load_eval_dataset(dataset_path: str) -> List[Dict[str, Any]]:
    path = Path(dataset_path)
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("评测数据必须是JSON数组。")
    return data


def evaluate_retrieval(dataset: List[Dict[str, Any]], top_k: int = 4) -> Dict[str, Any]:
    if not dataset:
        return {"sample_count": 0, "recall_at_k": 0.0, "precision_at_k": 0.0, "mrr": 0.0, "hit_rate": 0.0}

    hits = 0
    recall_sum = 0.0
    precision_sum = 0.0
    reciprocal_rank_sum = 0.0
    details: List[Dict[str, Any]] = []

    for sample in dataset:
        question = sample["question"]
        gold_chunk_ids = set(sample.get("gold_chunk_ids", []))
        candidates = _retrieve_candidates(question)[:top_k]
        retrieved_chunk_ids = [candidate["metadata"]["chunk_id"] for candidate in candidates]
        matched = [chunk_id for chunk_id in retrieved_chunk_ids if chunk_id in gold_chunk_ids]

        hit = 1 if matched else 0
        hits += hit

        recall = len(matched) / len(gold_chunk_ids) if gold_chunk_ids else 0.0
        precision = len(matched) / len(retrieved_chunk_ids) if retrieved_chunk_ids else 0.0
        recall_sum += recall
        precision_sum += precision

        reciprocal_rank = 0.0
        for index, chunk_id in enumerate(retrieved_chunk_ids, start=1):
            if chunk_id in gold_chunk_ids:
                reciprocal_rank = 1.0 / index
                break
        reciprocal_rank_sum += reciprocal_rank

        details.append(
            {
                "question": question,
                "gold_chunk_ids": list(gold_chunk_ids),
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "matched_chunk_ids": matched,
                "recall": recall,
                "precision": precision,
                "reciprocal_rank": reciprocal_rank,
            }
        )

    sample_count = len(dataset)
    return {
        "sample_count": sample_count,
        "recall_at_k": round(recall_sum / sample_count, 4),
        "precision_at_k": round(precision_sum / sample_count, 4),
        "mrr": round(reciprocal_rank_sum / sample_count, 4),
        "hit_rate": round(hits / sample_count, 4),
        "details": details,
    }


def evaluate_generation(dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not dataset:
        return {"sample_count": 0, "keypoint_coverage": 0.0, "details": []}

    coverage_sum = 0.0
    details: List[Dict[str, Any]] = []

    for sample in dataset:
        question = sample["question"]
        expected_points = sample.get("expected_points", [])
        rag_result = get_rag_response([question])
        answer = ""
        if rag_result.get("questions"):
            answer = rag_result["questions"][0].get("answer", "")

        matched_points = [point for point in expected_points if point in answer]
        coverage = len(matched_points) / len(expected_points) if expected_points else 0.0
        coverage_sum += coverage

        details.append(
            {
                "question": question,
                "answer": answer,
                "expected_points": expected_points,
                "matched_points": matched_points,
                "coverage": coverage,
            }
        )

    sample_count = len(dataset)
    return {
        "sample_count": sample_count,
        "keypoint_coverage": round(coverage_sum / sample_count, 4),
        "details": details,
    }


def run_eval(dataset_path: str) -> Dict[str, Any]:
    dataset = load_eval_dataset(dataset_path)
    result = evaluate_retrieval(dataset)
    ## result = evaluate_generation(dataset)
    return result


if __name__ == "__main__":
    sample_path = Path(__file__).with_name("rag_eval_sample.json")
    result = run_eval(str(sample_path))
    print(json.dumps(result, ensure_ascii=False, indent=2))
