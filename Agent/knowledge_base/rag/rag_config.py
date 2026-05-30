from pathlib import Path
from typing import Any, Dict, List

RAG_DIR = Path(__file__).resolve().parent
KNOWLEDGE_BASE_DIR = RAG_DIR.parent
DATA_DIR = RAG_DIR / "data"
OUTPUT_DIR = RAG_DIR / "output"
MACHINE_OUTPUT_DIR = OUTPUT_DIR / "machine"
REPORT_OUTPUT_DIR = OUTPUT_DIR / "reports"
RUNS_DIR = OUTPUT_DIR / "runs"
MEDICAL_OUTPUT_DIR = OUTPUT_DIR / "medical"
MEDICAL_MACHINE_OUTPUT_DIR = MEDICAL_OUTPUT_DIR / "machine"
MEDICAL_REPORT_OUTPUT_DIR = MEDICAL_OUTPUT_DIR / "reports"
SOURCE_DIR = KNOWLEDGE_BASE_DIR / "source"
DEFAULT_EMBEDDING_MODEL_PATH = KNOWLEDGE_BASE_DIR / "models" / "bge-small-zh-v1.5"

EVAL_DATASET_PATH = DATA_DIR / "ragas_generated_eval_dataset.json"
RAGCARE_QA_DIR = DATA_DIR / "external" / "ragcare_qa"
RAGCARE_QA_RAW_DIR = RAGCARE_QA_DIR / "raw"
RAGCARE_QA_PROCESSED_DIR = RAGCARE_QA_DIR / "processed"
RAGCARE_QA_DB_DIR = RAGCARE_QA_DIR / "db"
MEDICAL_CORPUS_PATH = RAGCARE_QA_PROCESSED_DIR / "medical_corpus_docs.jsonl"
MEDICAL_EVAL_DATASET_PATH = RAGCARE_QA_PROCESSED_DIR / "medical_eval_dataset.json"
MEDICAL_VECTOR_DB_DIR = RAGCARE_QA_DB_DIR / "chroma"

TRACE_STAGE_ORDER = [
    "dense_raw",
    "dense_thresholded",
    "dense_mmr",
    "sparse",
    "merged_before_rerank",
    "reranked",
    "final",
]

# 检索调参只改这里。字段名必须和 query_rag.RagRetrievalConfig 保持一致。
RETRIEVAL_PROFILES: Dict[str, Dict[str, Any]] = {
    "baseline_current": {
        "dense_fetch_k": 10,
        "dense_mmr_k": 6,
        "sparse_fetch_k": 8,
        "final_top_k": 4,
        "dense_score_threshold": 0.45,
        "final_rerank_threshold": 0.18,
        "mmr_lambda": 0.7,
        "official_only_when_available": True,
    },
    "candidate_top20": {
        "dense_fetch_k": 80,
        "dense_mmr_k": 40,
        "sparse_fetch_k": 80,
        "final_top_k": 20,
        "dense_score_threshold": 0.0,
        "final_rerank_threshold": 0.0,
        "mmr_lambda": 0.7,
        "official_only_when_available": True,
    },
    "more_diverse_mmr": {
        "dense_fetch_k": 80,
        "dense_mmr_k": 40,
        "sparse_fetch_k": 80,
        "final_top_k": 20,
        "dense_score_threshold": 0.0,
        "final_rerank_threshold": 0.0,
        "mmr_lambda": 0.4,
        "official_only_when_available": True,
    },
}

# retrieval eval 的 single/sweep 都从这里取参数，不需要命令行传参。
RETRIEVAL_EVAL_CONFIG = {
    "mode": "sweep",
    "dataset_path": str(EVAL_DATASET_PATH),
    "output_path": str(MACHINE_OUTPUT_DIR / "rag_eval_result.json"),
    "sweep_output_path": str(MACHINE_OUTPUT_DIR / "rag_eval_sweep_result.json"),
    "report_path": str(REPORT_OUTPUT_DIR / "rag_eval_report.md"),
    "sweep_report_path": str(REPORT_OUTPUT_DIR / "rag_eval_sweep_report.md"),
    "limit": None,
    "top_k": None,
    "retrieval_profile": "baseline_current",
    "save_output": True,
    "save_markdown": True,
}

RETRIEVAL_SWEEP_CONFIGS: List[Dict[str, Any]] = [
    {"name": "baseline_current", "config": RETRIEVAL_PROFILES["baseline_current"]},
    {"name": "candidate_top20", "config": RETRIEVAL_PROFILES["candidate_top20"]},
    {"name": "more_diverse_mmr", "config": RETRIEVAL_PROFILES["more_diverse_mmr"]},
]

CANDIDATE_GENERATION_CONFIG = {
    "dataset_path": str(EVAL_DATASET_PATH),
    "output_path": str(MACHINE_OUTPUT_DIR / "rag_eval_candidates_top20.json"),
    "top_k": 20,
    "limit": None,
    "retrieval_profile": "candidate_top20",
}

RAGAS_ACTIVE_PROFILE = "reviewed_all_core_metrics"

RAGAS_BASE_CONFIG = {
    "dataset_path": str(EVAL_DATASET_PATH),
    "ragas_dataset_path": str(MACHINE_OUTPUT_DIR / "ragas_eval_dataset.json"),
    "output_path": str(MACHINE_OUTPUT_DIR / "ragas_eval_result.json"),
    "report_path": str(REPORT_OUTPUT_DIR / "ragas_eval_report.md"),
    "score_cache_path": str(MACHINE_OUTPUT_DIR / "ragas_eval_score_cache.json"),
    "retrieval_eval_path": str(MACHINE_OUTPUT_DIR / "rag_eval_result.json"),
    "low_score_cases_path": str(MACHINE_OUTPUT_DIR / "ragas_low_score_cases.json"),
    "cross_metric_cases_path": str(MACHINE_OUTPUT_DIR / "ragas_cross_metric_bad_cases.json"),
    "limit": 1,
    "sample_filter": {
        "review_statuses": [],
        "question_types": [],
        "is_smoke_case": None,
    },
    "selected_metrics": ["faithfulness"],
    "include_reference_metrics": True,
    "run_ragas": True,
    "reuse_prepared_dataset": True,
    "reuse_score_cache": True,
    "save_dataset": True,
    "save_output": True,
    "save_markdown": True,
    "max_contexts": 3,
    "max_context_chars": 700,
    "max_response_chars": 900,
    "ragas_timeout": 600,
    "ragas_max_workers": 1,
    "answer_relevancy_strictness": 1,
    "judge_profile": "fast_quick_check",
    "repeat_count": 1,
    "low_score_threshold": 0.5,
    "retrieval_recall_low_threshold": 0.67,
    "retrieval_mrr_low_threshold": 0.5,
    "retrieval_profile": "baseline_current",
    "show_progress": False,
    "print_full_output": False,
}

RAGAS_RUN_PROFILES = {
    "quick_cached": {
        "limit": 1,
        "selected_metrics": ["faithfulness"],
        "reuse_prepared_dataset": True,
        "reuse_score_cache": True,
        "ragas_timeout": 600,
        "ragas_max_workers": 1,
        "judge_profile": "fast_quick_check",
        "repeat_count": 1,
    },
    "reviewed_5_core_metrics": {
        "limit": 5,
        "selected_metrics": [
            "faithfulness",
            "answer_relevancy",
            "context_utilization",
            "context_recall",
        ],
        "reuse_prepared_dataset": True,
        "reuse_score_cache": False,
        "ragas_timeout": 900,
        "ragas_max_workers": 2,
        "judge_profile": "fast_core",
        "repeat_count": 1,
    },
    "reviewed_all_core_metrics": {
        "limit": None,
        "selected_metrics": [
            "faithfulness",
            "answer_relevancy",
            "context_utilization",
            "context_recall",
        ],
        "reuse_prepared_dataset": True,
        "reuse_score_cache": False,
        "ragas_timeout": 1200,
        "ragas_max_workers": 2,
        "judge_profile": "standard_single",
        "repeat_count": 1,
    },
    "strict_generated_repeat3": {
        "dataset_path": str(EVAL_DATASET_PATH),
        "limit": None,
        "selected_metrics": [
            "faithfulness",
            "answer_relevancy",
            "context_utilization",
            "context_recall",
        ],
        "reuse_prepared_dataset": True,
        "reuse_score_cache": False,
        "ragas_timeout": 1500,
        "ragas_max_workers": 1,
        "judge_profile": "strict_generated_repeat3",
        "repeat_count": 3,
        "low_score_threshold": 0.6,
        "retrieval_recall_low_threshold": 0.8,
        "retrieval_mrr_low_threshold": 0.75,
    },
    "reviewed_all_prepare_only": {
        "limit": None,
        "selected_metrics": ["faithfulness"],
        "run_ragas": False,
        "reuse_prepared_dataset": True,
        "reuse_score_cache": False,
        "judge_profile": "prepare_only",
        "repeat_count": 0,
    },
}

if RAGAS_ACTIVE_PROFILE not in RAGAS_RUN_PROFILES:
    raise ValueError(f"Unknown RAGAS_ACTIVE_PROFILE: {RAGAS_ACTIVE_PROFILE}")

RAGAS_RUN_CONFIG = {
    **RAGAS_BASE_CONFIG,
    **RAGAS_RUN_PROFILES[RAGAS_ACTIVE_PROFILE],
    "active_profile": RAGAS_ACTIVE_PROFILE,
}

RUN_PIPELINE_CONFIG = {
    "run_name": "local_pipeline",
    "steps": ["validate_datasets", "trace_export", "summary"],
    "copy_latest_outputs_to_run_dir": True,
    "thresholds": {
        "retrieval_hit_rate_min": 1.0,
        "retrieval_recall_at_k_min": 0.6,
        "ragas_faithfulness_min": 0.5,
        "claim_coverage_min": 0.75,
        "evidence_support_rate_min": 0.65,
        "judge_failed_count_max": 0,
    },
    "print_full_output": False,
}

RAGAS_TESTSET_GENERATE_CONFIG = {
    "mode": "generate",
    "source_dir": str(SOURCE_DIR),
    "embedding_model_path": str(DEFAULT_EMBEDDING_MODEL_PATH),
    "embedding_device": "cpu",
    "raw_output_path": str(MACHINE_OUTPUT_DIR / "ragas_generated_testset.json"),
    "converted_output_path": str(MACHINE_OUTPUT_DIR / "ragas_generated_eval_samples.json"),
    "eval_dataset_path": str(EVAL_DATASET_PATH),
    "testset_size": 2,
    "max_pages_per_pdf": 10,
    "write_eval_dataset": True,
    "save_machine_output": True,
    "llm_preflight_enabled": True,
    "run_config_timeout": 1200,
    "run_config_max_workers": 1,
    "print_full_output": False,
}

RAGCARE_QA_PREPARE_CONFIG = {
    "raw_dir": str(RAGCARE_QA_RAW_DIR),
    "corpus_output_path": str(MEDICAL_CORPUS_PATH),
    "eval_output_path": str(MEDICAL_EVAL_DATASET_PATH),
    "limit": None,
    "review_status": "pending_human_review",
    "source_dataset": "ChatMED-Project/RAGCare-QA",
    "print_full_output": False,
}

MEDICAL_EMBEDDING_CONFIG = {
    "provider": "openai_compatible",
    "api_key_env": "MEDICAL_EMBEDDING_API_KEY",
    "base_url_env": "MEDICAL_EMBEDDING_BASE_URL",
    "model_env": "MEDICAL_EMBEDDING_MODEL",
    "default_model": "text-embedding-3-small",
    "batch_size": 32,
    "chunk_size": 700,
    "chunk_overlap": 100,
    "persist_directory": str(MEDICAL_VECTOR_DB_DIR),
    "collection_name": "ragcare_qa_medical",
}

MEDICAL_KNOWLEDGE_BUILD_CONFIG = {
    "corpus_path": str(MEDICAL_CORPUS_PATH),
    "persist_directory": str(MEDICAL_VECTOR_DB_DIR),
    "collection_name": "ragcare_qa_medical",
    "chunk_size": 700,
    "chunk_overlap": 100,
    "embedding_config": MEDICAL_EMBEDDING_CONFIG,
    "print_full_output": False,
}

MEDICAL_RETRIEVAL_EVAL_CONFIG = {
    "corpus_path": str(MEDICAL_CORPUS_PATH),
    "dataset_path": str(MEDICAL_EVAL_DATASET_PATH),
    "output_path": str(MEDICAL_MACHINE_OUTPUT_DIR / "medical_retrieval_eval_result.json"),
    "report_path": str(MEDICAL_REPORT_OUTPUT_DIR / "medical_retrieval_eval_report.md"),
    "top_k": 5,
    "limit": 20,
    "save_output": True,
    "save_markdown": True,
    "print_full_output": False,
}
