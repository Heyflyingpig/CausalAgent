from pathlib import Path
from typing import Any, Dict, List

RAG_DIR = Path(__file__).resolve().parent  # rag 子目录根路径。
KNOWLEDGE_BASE_DIR = RAG_DIR.parent  # knowledge_base 根路径。
DATA_DIR = RAG_DIR / "data"  # RAG 数据集和外部数据目录。
OUTPUT_DIR = RAG_DIR / "output"  # RAG 评测输出根目录。
MACHINE_OUTPUT_DIR = OUTPUT_DIR / "machine"  # JSON / JSONL 等机器可读输出目录。
REPORT_OUTPUT_DIR = OUTPUT_DIR / "reports"  # Markdown 报告输出目录。
RUNS_DIR = OUTPUT_DIR / "runs"  # 每次 pipeline run 的快照目录。
SOURCE_DIR = KNOWLEDGE_BASE_DIR / "source"  # 旧因果资料源文档目录。
DEFAULT_EMBEDDING_MODEL_PATH = KNOWLEDGE_BASE_DIR / "models" / "bge-small-zh-v1.5"  # 默认本地 embedding。
VECTOR_DB_DIR = KNOWLEDGE_BASE_DIR / "db"  # 当前向量库持久化目录，禁止随意清空。

PUBMEDQA_DIR = DATA_DIR / "external" / "pubmedqa"  # PubMedQA active 数据集根目录。
PUBMEDQA_PROCESSED_DIR = PUBMEDQA_DIR / "processed"  # PubMedQA 转换后数据目录。
PUBMEDQA_CORPUS_PATH = PUBMEDQA_PROCESSED_DIR / "pubmedqa_corpus_docs.jsonl"  # PubMedQA evidence corpus。
PUBMEDQA_EVAL_DATASET_PATH = PUBMEDQA_PROCESSED_DIR / "pubmedqa_eval_dataset.json"  # PubMedQA benchmark_v2 主测试集。
EVAL_DATASET_PATH = PUBMEDQA_EVAL_DATASET_PATH  # 兼容旧工具名，实际指向 PubMedQA active 测试集。
MEDICAL_VECTOR_DB_DIR = VECTOR_DB_DIR  # 医疗向量库仍写入项目统一 db 目录。
ACTIVE_BENCHMARK_NAME = "pubmedqa"  # 当前 active benchmark 名称。
ACTIVE_CORPUS_PATH = PUBMEDQA_CORPUS_PATH  # 当前 active benchmark 对应 corpus。
ACTIVE_EVAL_DATASET_PATH = PUBMEDQA_EVAL_DATASET_PATH  # 当前 active benchmark 对应测试集。

"""
定义 retrieval trace 的阶段顺序；报告、trace 导出和阶段命中/丢失分析会按这个顺序展示。
"""
TRACE_STAGE_ORDER = [
    "dense_raw",  # dense 向量检索原始候选。
    "dense_thresholded",  # dense 分数阈值过滤后的候选。
    "dense_mmr",  # dense MMR 去重后的候选。
    "sparse",  # BM25 / sparse 检索候选。
    "merged_before_rerank",  # dense 与 sparse 合并后的候选。
    "reranked",  # 合并候选 rerank 后的顺序。
    "final",  # 最终进入 answer / Ragas contexts 的证据。
]

"""
定义所有可复用的检索参数 profile；retrieval_eval、Ragas prepared dataset 和 sweep 调参都按 profile 名称读取。
"""
RETRIEVAL_PROFILES: Dict[str, Dict[str, Any]] = {
    "baseline_current": {  # 旧因果/Pearl benchmark 当前基线。
        "dense_fetch_k": 10,  # dense 第一阶段取回候选数。
        "dense_mmr_k": 6,  # dense MMR 后保留候选数。
        "sparse_fetch_k": 8,  # sparse / BM25 取回候选数。
        "final_top_k": 4,  # 最终进入 answer / Ragas contexts 的证据数。
        "dense_score_threshold": 0.45,  # dense 原始候选最低分数。
        "final_rerank_threshold": 0.18,  # final 阶段 rerank 最低分数。
        "mmr_lambda": 0.7,  # MMR 权重；越大越偏相关性，越小越偏多样性。
        "official_only_when_available": True,  # 旧因果库有官方语料时只保留官方语料。
    },
    "candidate_top20": {  # 旧因果/Pearl top20 候选生成配置。
        "dense_fetch_k": 80,  # 放大 dense 候选池，便于观察召回上限。
        "dense_mmr_k": 40,  # 放大 MMR 后 dense 候选数。
        "sparse_fetch_k": 80,  # 放大 sparse 候选池。
        "final_top_k": 20,  # 最终保留 top20 作为候选分析输出。
        "dense_score_threshold": 0.0,  # 不过滤 dense 分数。
        "final_rerank_threshold": 0.0,  # 不过滤 final rerank 分数。
        "mmr_lambda": 0.7,  # MMR 偏相关性。
        "official_only_when_available": True,  # 旧因果库有官方语料时只保留官方语料。
    },
    "more_diverse_mmr": {  # 旧因果/Pearl 多样性更强的 MMR 对照配置。
        "dense_fetch_k": 80,  # 放大 dense 候选池。
        "dense_mmr_k": 40,  # 放大 MMR 后 dense 候选数。
        "sparse_fetch_k": 80,  # 放大 sparse 候选池。
        "final_top_k": 20,  # 最终保留 top20。
        "dense_score_threshold": 0.0,  # 不过滤 dense 分数。
        "final_rerank_threshold": 0.0,  # 不过滤 final rerank 分数。
        "mmr_lambda": 0.4,  # 降低相关性权重，提高多样性。
        "official_only_when_available": True,  # 旧因果库有官方语料时只保留官方语料。
    },
    "active_current": {  # 当前 active benchmark 基线。
        "dense_fetch_k": 10,  # dense 第一阶段取回候选数。
        "dense_mmr_k": 10,  # 当前等于 dense_fetch_k，通常不会触发二次 MMR embedding。
        "sparse_fetch_k": 8,  # sparse / BM25 取回候选数。
        "final_top_k": 4,  # PubMedQA smoke20/pilot100 显示 top4 与 top12 召回持平，优先减少 Ragas 上下文噪音。
        "dense_score_threshold": 0.45,  # dense 原始候选最低分数。
        "final_rerank_threshold": 0.0,  # final 阶段不再按 rerank 分数过滤，避免截掉 sparse 命中的 gold。
        "mmr_lambda": 0.7,  # MMR 偏相关性。
        "official_only_when_available": False,  # 医疗 benchmark corpus 不做官方/非官方语料过滤。
    },
    "pubmedqa_eval100": {  # PubMedQA 100 条正式评测检索预设。
        "dense_fetch_k": 10,  # 保持当前 active 基线，优先稳定性而不是扩大候选池。
        "dense_mmr_k": 10,  # 与 dense_fetch_k 相同，避免额外 MMR embedding 成本。
        "sparse_fetch_k": 8,  # 保持当前 active 基线。
        "final_top_k": 4,  # 100 条正式评测继续使用低噪音 top4。
        "dense_score_threshold": 0.45,  # 保持当前 active 基线。
        "final_rerank_threshold": 0.0,  # 不按 rerank 分数截断，避免误丢 gold。
        "mmr_lambda": 0.7,  # 偏相关性，减少正式评测波动。
        "official_only_when_available": False,  # 医疗 benchmark corpus 不做官方/非官方语料过滤。
    },
    "active_candidate_top20": {  # 当前 active benchmark top20 调参候选配置。
        "dense_fetch_k": 80,  # 放大 dense 候选池，观察召回上限。
        "dense_mmr_k": 40,  # 放大 MMR 后 dense 候选数；会触发候选文本 embedding。
        "sparse_fetch_k": 80,  # 放大 sparse 候选池。
        "final_top_k": 20,  # 最终保留 top20。
        "dense_score_threshold": 0.0,  # 不过滤 dense 分数。
        "final_rerank_threshold": 0.0,  # 不过滤 final rerank 分数。
        "mmr_lambda": 0.7,  # MMR 偏相关性。
        "official_only_when_available": False,  # 医疗 benchmark corpus 不做官方/非官方语料过滤。
    },
    "active_more_diverse_mmr": {  # 当前 active benchmark 多样性更强的 MMR 对照配置。
        "dense_fetch_k": 80,  # 放大 dense 候选池。
        "dense_mmr_k": 40,  # 放大 MMR 后 dense 候选数；会触发候选文本 embedding。
        "sparse_fetch_k": 80,  # 放大 sparse 候选池。
        "final_top_k": 20,  # 最终保留 top20。
        "dense_score_threshold": 0.0,  # 不过滤 dense 分数。
        "final_rerank_threshold": 0.0,  # 不过滤 final rerank 分数。
        "mmr_lambda": 0.4,  # 降低相关性权重，提高多样性。
        "official_only_when_available": False,  # 医疗 benchmark corpus 不做官方/非官方语料过滤。
    },
}

VISIBLE_RETRIEVAL_PROFILES = [
    "active_current",
    "pubmedqa_eval100",
]

VISIBLE_RETRIEVAL_PROFILE_LIMITS = {
    "active_current": 30,
    "pubmedqa_eval100": 100,
}

"""
定义 retrieval_eval 的主运行配置；single 模式跑当前 profile，sweep 模式比较多个 retrieval profile。
"""
RETRIEVAL_EVAL_CONFIG = {
    "mode": "single",  # single 跑一组 profile；sweep 跑 RETRIEVAL_SWEEP_CONFIGS。
    "dataset_path": str(ACTIVE_EVAL_DATASET_PATH),  # retrieval_eval 使用的 benchmark_v2 测试集。
    "output_path": str(MACHINE_OUTPUT_DIR / "rag_eval_result.json"),  # single 模式 JSON 输出。
    "sweep_output_path": str(MACHINE_OUTPUT_DIR / "rag_eval_sweep_result.json"),  # sweep 模式 JSON 输出。
    "report_path": str(REPORT_OUTPUT_DIR / "rag_eval_report.md"),  # single 模式 Markdown 报告。
    "sweep_report_path": str(REPORT_OUTPUT_DIR / "rag_eval_sweep_report.md"),  # sweep 模式 Markdown 报告。
    "limit": 30,  # 当前 smoke/pilot 默认跑前 30 条；全量评测时再改为 None。
    "top_k": None,  # 非 None 时临时覆盖 final_top_k；正式调参优先改 profile。
    "retrieval_profile": "active_current",  # single 模式使用的检索 profile。
    "save_output": True,  # 是否写 JSON 输出。
    "save_markdown": True,  # 是否写 Markdown 报告。
}

"""
定义 retrieval sweep 的候选 profile 列表；这里只做检索评测，不调用 answer build 或 judge。
"""
RETRIEVAL_SWEEP_CONFIGS: List[Dict[str, Any]] = [
    {
        "name": "active_top4",
        "config": RETRIEVAL_PROFILES["active_current"],
    },  # 当前 active 基线，最小 Ragas contexts 候选。
    {
        "name": "active_top6",
        "config": {**RETRIEVAL_PROFILES["active_current"], "final_top_k": 6},
    },  # 小上下文候选，观察 top5 是否保持命中。
    {
        "name": "active_top8",
        "config": {**RETRIEVAL_PROFILES["active_current"], "final_top_k": 8},
    },  # 中等上下文候选。
    {
        "name": "active_top10",
        "config": {**RETRIEVAL_PROFILES["active_current"], "final_top_k": 10},
    },  # 接近当前基线的较短上下文。
    {
        "name": "active_top12",
        "config": {**RETRIEVAL_PROFILES["active_current"], "final_top_k": 12},
    },  # 调参保留项，用于和旧 top12 基线对照。
]

"""
定义旧候选生成工具的配置；用于离线生成 top-k 候选表，不是当前 active benchmark 主入口。
"""
CANDIDATE_GENERATION_CONFIG = {
    "dataset_path": str(ACTIVE_EVAL_DATASET_PATH),  # PubMedQA active benchmark 路径。
    "output_path": str(MACHINE_OUTPUT_DIR / "rag_eval_candidates_top20.json"),  # 离线候选表输出。
    "top_k": 20,  # 候选表保留 top-k。
    "limit": None,  # None 处理 active benchmark 全量。
    "retrieval_profile": "active_candidate_top20",  # 候选生成使用的 active profile。
}

RAGAS_ACTIVE_PROFILE = "pubmedqa_pipeline"  # 当前 Ragas profile；由 RAGAS_RUN_PROFILES 合并成运行配置。

"""
定义 Ragas 评测基础配置；最终配置会由这里和 RAGAS_ACTIVE_PROFILE 对应 profile 合并得到。
"""
RAGAS_BASE_CONFIG = {
    "dataset_path": str(ACTIVE_EVAL_DATASET_PATH),  # Ragas prepared dataset 的源测试集。
    "ragas_dataset_path": str(MACHINE_OUTPUT_DIR / "ragas_eval_dataset.json"),  # retrieval+answer 缓存。
    "output_path": str(MACHINE_OUTPUT_DIR / "ragas_eval_result.json"),  # Ragas judge 结果输出。
    "report_path": str(REPORT_OUTPUT_DIR / "ragas_eval_report.md"),  # Ragas Markdown 报告。
    "score_cache_path": str(MACHINE_OUTPUT_DIR / "ragas_eval_score_cache.json"),  # Ragas 分数缓存。
    "retrieval_eval_path": str(MACHINE_OUTPUT_DIR / "rag_eval_result.json"),  # 跨指标 bad case 对照的 retrieval 结果。
    "retrieval_report_path": str(REPORT_OUTPUT_DIR / "rag_eval_report.md"),  # Ragas 单跑时同步刷新的 retrieval 报告。
    "low_score_cases_path": str(MACHINE_OUTPUT_DIR / "ragas_low_score_cases.json"),  # Ragas 低分样本输出。
    "cross_metric_cases_path": str(MACHINE_OUTPUT_DIR / "ragas_cross_metric_bad_cases.json"),  # retrieval/Ragas 跨指标坏例。
    "limit": 1,  # base 默认只跑 1 条；最终由 active profile 覆盖。
    "sample_filter": {
        "review_statuses": [],  # 兼容旧字段；主 benchmark_v2 不新增 review_status。
        "question_types": [],  # 可按题型过滤；空列表表示不过滤。
        "is_smoke_case": None,  # 兼容旧字段；主 benchmark_v2 不新增 is_smoke_case。
    },
    "selected_metrics": ["faithfulness"],  # base 默认指标；最终由 active profile 覆盖。
    "include_reference_metrics": True,  # 是否启用依赖 reference 的指标，如 context_recall。
    "run_ragas": True,  # False 时只构造 prepared dataset，不调用 judge。
    "reuse_prepared_dataset": True,  # 签名一致时复用 ragas_eval_dataset.json。
    "reuse_score_cache": True,  # 签名一致时复用 ragas_eval_score_cache.json。
    "save_dataset": True,  # 是否保存 prepared dataset。
    "save_output": True,  # 是否保存 Ragas JSON 结果。
    "save_markdown": True,  # 是否保存 Ragas Markdown 报告。
    "max_contexts": 6,  # 送入 Ragas 的最多 contexts 数；PubMedQA reference 往往需要多段摘要覆盖。
    "max_context_chars": 1600,  # 单个 context 最大字符数；减少摘要/结论被截断导致的 context_recall 偏低。
    "max_response_chars": 1100,  # answer 最大字符数。
    "ragas_timeout": 600,  # Ragas 单任务超时秒数。
    "ragas_max_workers": 1,  # Ragas 并发 worker 数。
    "ragas_max_retries": 3,  # Ragas 单任务失败后的最大重试次数；避免默认 10 次把限流拖成小时级等待。
    "ragas_max_wait": 20,  # Ragas 重试指数退避的最大等待秒数。
    "answer_relevancy_strictness": 1,  # answer_relevancy 采样严格度；兼容部分 OpenAI-compatible API。
    "judge_profile": "fast_quick_check",  # judge 运行标签，进入缓存签名。
    "repeat_count": 1,  # Ragas judge 重复次数。
    "low_score_threshold": 0.5,  # Ragas 低分坏例阈值。
    "retrieval_recall_low_threshold": 0.67,  # 跨指标坏例中 retrieval recall 低分阈值。
    "retrieval_mrr_low_threshold": 0.5,  # 跨指标坏例中 retrieval MRR 低分阈值。
    "retrieval_profile": "active_current",  # Ragas prepared dataset 使用的检索 profile。
    "refresh_retrieval_eval_before_ragas": True,  # 单独跑 Ragas 前先保证 retrieval latest 与本次样本一致。
    "show_progress": False,  # 是否显示 Ragas 进度条。
}

"""
定义 Ragas 运行 profile；用于区分 quick smoke、小样本核心指标、全量、prepare-only 和 active repeat 场景。
"""
RAGAS_RUN_PROFILES = {
    "quick_cached": {  # 最小链路检查：验证脚本和缓存是否可用。
        "limit": 1,  # 只跑 1 条。
        "selected_metrics": ["faithfulness"],  # 只跑最轻量核心指标。
        "reuse_prepared_dataset": True,  # 允许复用 prepared dataset。
        "reuse_score_cache": True,  # 允许复用 Ragas 分数缓存。
        "ragas_timeout": 600,  # 单任务超时秒数。
        "ragas_max_workers": 1,  # 单 worker，降低 API 压力。
        "judge_profile": "fast_quick_check",  # judge 标签，进入缓存签名。
        "repeat_count": 1,  # judge 不重复。
    },
    "reviewed_5_core_metrics": {  # 小样本四指标检查。
        "limit": 5,  # 只跑前 5 条。
        "selected_metrics": [
            "faithfulness",  # 回答是否忠于证据。
            "answer_relevancy",  # 回答是否切题。
            "context_utilization",  # 回答是否有效利用上下文。
            "context_recall",  # 上下文是否覆盖 reference 要点。
        ],
        "reuse_prepared_dataset": True,  # 签名一致时复用 prepared dataset。
        "reuse_score_cache": False,  # 小样本复评默认重新 judge。
        "ragas_timeout": 900,  # 单任务超时秒数。
        "ragas_max_workers": 2,  # Ragas 并发 worker 数。
        "ragas_max_retries": 3,  # 小样本检查保留有限重试。
        "ragas_max_wait": 20,  # 限制单次失败后的最长等待。
        "judge_profile": "fast_core",  # judge 标签，进入缓存签名。
        "repeat_count": 1,  # judge 不重复。
    },
    "pubmedqa_pipeline": {  # PubMedQA pipeline 调参入口；样本数可通过前端动态覆盖。
        "limit": 30,  # 只跑前 30 条。
        "selected_metrics": [
            "faithfulness",  # 回答是否忠于证据。
            "answer_relevancy",  # 回答是否切题。
            "context_utilization",  # 回答是否有效利用上下文。
            "context_recall",  # 上下文是否覆盖 reference 要点。
        ],
        "reuse_prepared_dataset": True,  # 签名不一致时会自动重建 prepared dataset。
        "reuse_score_cache": False,  # 调参 smoke 默认重新 judge。
        "retrieval_config": {
            **RETRIEVAL_PROFILES["active_current"],
            "max_evidence_chars": 1600,
        },  # Ragas 需要完整 PubMedQA rationale；只覆盖评测链路，不改业务默认证据长度。
        "ragas_timeout": 3600,  # 单任务超时秒数；30 条 Ragas smoke 给 judge 最多 1 小时。
        "ragas_max_workers": 5,  # smoke 允许轻量并发，避免四指标串行过慢。
        "ragas_max_retries": 3,  # 避免限流时默认 10 次重试拖长整体耗时。
        "ragas_max_wait": 20,  # 限制重试退避最长等待。
        "judge_profile": "pubmedqa_pipeline_ctx6_1600_evidence1600_pubmedqa_prompt_v6",  # judge 标签，进入缓存签名。
        "repeat_count": 1,  # judge 不重复。
    },
    "pubmedqa_eval100": {  # PubMedQA 100 条正式评测配置。
        "limit": 100,  # 只跑前 100 条。
        "selected_metrics": [
            "faithfulness",  # 回答是否忠于证据。
            "answer_relevancy",  # 回答是否切题。
            "context_utilization",  # 回答是否有效利用上下文。
            "context_recall",  # 上下文是否覆盖 reference 要点。
        ],
        "reuse_prepared_dataset": True,  # 中断或重跑时优先复用 prepared dataset。
        "reuse_score_cache": False,  # 正式评测默认重新 judge。
        "retrieval_profile": "pubmedqa_eval100",  # 与 100 条检索预设对应。
        "retrieval_config": {
            **RETRIEVAL_PROFILES["pubmedqa_eval100"],
            "max_evidence_chars": 1600,
        },  # 保持 PubMedQA rationale 覆盖。
        "ragas_timeout": 1800,  # 100 条长跑保守给足单任务超时。
        "ragas_max_workers": 8,  # Ragas 0.4.x 会按样本×指标提交异步任务；5 worker 先保守并发提速。
        "ragas_max_retries": 3,  # 控制 API 失败重试次数，避免限流时长时间空等。
        "ragas_max_wait": 20,  # 控制 retry 指数退避最长等待。
        "judge_profile": "pubmedqa_eval100_ctx6_1600_evidence1600_pubmedqa_prompt_v6",  # judge 标签，进入缓存签名。
        "repeat_count": 1,  # judge 不重复。
    },
    "reviewed_all_core_metrics": {  # 当前 active benchmark 全量四指标配置。
        "limit": None,  # None 表示完整 active benchmark。
        "selected_metrics": [
            "faithfulness",  # 回答是否忠于证据。
            "answer_relevancy",  # 回答是否切题。
            "context_utilization",  # 回答是否有效利用上下文。
            "context_recall",  # 上下文是否覆盖 reference 要点。
        ],
        "reuse_prepared_dataset": True,  # 全量中断后优先复用 prepared dataset。
        "reuse_score_cache": False,  # 正式全量默认重新 judge。
        "ragas_timeout": 1200,  # 单任务超时秒数。
        "ragas_max_workers": 2,  # Ragas 并发 worker 数。
        "judge_profile": "standard_single",  # judge 标签，进入缓存签名。
        "repeat_count": 1,  # judge 不重复。
    },
    "strict_repeat3": {  # active benchmark 重复评测，用于观察 judge 方差。
        "dataset_path": str(ACTIVE_EVAL_DATASET_PATH),  # PubMedQA active benchmark。
        "limit": None,  # active benchmark 全量。
        "selected_metrics": [
            "faithfulness",  # 回答是否忠于证据。
            "answer_relevancy",  # 回答是否切题。
            "context_utilization",  # 回答是否有效利用上下文。
            "context_recall",  # 上下文是否覆盖 reference 要点。
        ],
        "reuse_prepared_dataset": True,  # 签名一致时复用 prepared dataset。
        "reuse_score_cache": False,  # 严格复评默认重新 judge。
        "ragas_timeout": 1500,  # 单任务超时秒数。
        "ragas_max_workers": 1,  # 单 worker，降低 judge 方差和 API 压力。
        "judge_profile": "strict_repeat3",  # judge 标签，进入缓存签名。
        "repeat_count": 3,  # 每条重复 judge 3 次。
        "low_score_threshold": 0.6,  # 更严格的 Ragas 低分阈值。
        "retrieval_recall_low_threshold": 0.8,  # 更严格的 retrieval recall 阈值。
        "retrieval_mrr_low_threshold": 0.75,  # 更严格的 retrieval MRR 阈值。
    },
    "reviewed_all_prepare_only": {  # 只生成 prepared dataset，不调用 Ragas judge。
        "limit": None,  # active benchmark 全量。
        "selected_metrics": ["faithfulness"],  # 占位指标；run_ragas=False 时不实际 judge。
        "run_ragas": False,  # 只准备数据，不运行 Ragas。
        "reuse_prepared_dataset": True,  # 签名一致时复用 prepared dataset。
        "reuse_score_cache": False,  # 不使用分数缓存。
        "judge_profile": "prepare_only",  # 运行标签。
        "repeat_count": 0,  # 不运行 judge。
    },
}

VISIBLE_RAGAS_PROFILES = [
    "pubmedqa_pipeline",
    "pubmedqa_eval100",
]

if RAGAS_ACTIVE_PROFILE not in RAGAS_RUN_PROFILES:
    raise ValueError(f"Unknown RAGAS_ACTIVE_PROFILE: {RAGAS_ACTIVE_PROFILE}")

"""
合成 ragas_eval.py 实际读取的 Ragas 运行配置；active profile 会覆盖 base 默认项。
"""
RAGAS_RUN_CONFIG = {
    **RAGAS_BASE_CONFIG,  # 基础默认项。
    **RAGAS_RUN_PROFILES[RAGAS_ACTIVE_PROFILE],  # active profile 覆盖基础默认项。
    "active_profile": RAGAS_ACTIVE_PROFILE,  # 记录实际启用的 profile 名称。
}

"""
定义统一 RAG 评测 pipeline 的运行步骤、run 快照和回归阈值；run_rag_eval.py 按这里执行。
"""
RUN_PIPELINE_CONFIG = {
    "run_name": "active_benchmark_full_pipeline",  # run snapshot 目录名后缀。
    "steps": ["validate_datasets", "retrieval_eval", "ragas_eval", "trace_export", "summary"],  # 默认保留坏例链路导出；claim 需人工启用。
    "copy_latest_outputs_to_run_dir": True,  # 是否把 latest 输出复制到本次 run 目录。
    "thresholds": {
        "retrieval_hit_rate_min": 1.0,  # final 证据命中率最低阈值。
        "retrieval_recall_at_k_min": 0.6,  # final 证据 recall 最低阈值。
        "ragas_faithfulness_min": 0.5,  # Ragas faithfulness 最低阈值。
    },
}

"""
定义 Ragas generated testset 的生成配置；当前 active benchmark 不使用它，这里仅保留工具兼容。
"""
RAGAS_TESTSET_GENERATE_CONFIG = {
    "mode": "generate",  # Ragas generated testset 工具运行模式。
    "source_dir": str(SOURCE_DIR),  # 旧因果资料源文档目录。
    "embedding_provider": "medical_openai_compatible",  # 复用 build_knowledge._build_medical_embedding()。
    "raw_output_path": str(MACHINE_OUTPUT_DIR / "ragas_generated_testset.json"),  # Ragas 原始测试集输出。
    "converted_output_path": str(MACHINE_OUTPUT_DIR / "ragas_generated_eval_samples.json"),  # 转换后样本输出。
    "eval_dataset_path": str(ACTIVE_EVAL_DATASET_PATH),  # 默认写入 PubMedQA active benchmark 路径。
    "testset_size": 2,  # 生成样本数量。
    "max_pages_per_pdf": 10,  # 每个 PDF 最多读取页数。
    "write_eval_dataset": True,  # 是否写 benchmark JSON。
    "save_machine_output": True,  # 是否保存机器可读输出。
    "llm_preflight_enabled": True,  # 生成前是否检查 LLM 可用性。
    "llm_max_tokens": 4096,  # Ragas 结构化抽取输出上限，避免默认 token 太小导致截断。
    "run_config_timeout": 1200,  # Ragas 生成超时秒数。
    "run_config_max_workers": 1,  # Ragas 生成 worker 数。
    "raise_exceptions": False,  # 单个 Ragas transform 节点失败时继续生成，便于 smoke。
}

"""
定义 PubMedQA active benchmark 的转换配置；prepare_pubmedqa.py 用它生成 corpus 和 benchmark_v2 测试集。
"""
PUBMEDQA_PREPARE_CONFIG = {
    "dataset_name": "pubmed_qa",  # Hugging Face dataset 名称。
    "subset_name": "pqa_labeled",  # PubMedQA 人工标注子集。
    "split": "train",  # PubMedQA labeled split。
    "cache_arrow_path": "",  # 可选本地 Arrow 文件路径；为空时走 Hugging Face load_dataset。
    "corpus_output_path": str(PUBMEDQA_CORPUS_PATH),  # 转换后的 evidence corpus。
    "eval_output_path": str(PUBMEDQA_EVAL_DATASET_PATH),  # 转换后的 benchmark_v2 候选测试集。
    "limit": None,  # None 转换 PubMedQA labeled 全量；调试可设 20/100。
    "source_dataset": "pubmed_qa/pqa_labeled",  # 写入 source 元数据的数据集名。
}

"""
定义医疗知识库的 OpenAI-compatible embedding 配置；这里只记录环境变量名和构建参数，不写真实密钥。
"""
MEDICAL_EMBEDDING_CONFIG = {
    "provider": "openai_compatible",  # 医疗库使用 OpenAI-compatible embedding。
    "api_key_env": "MEDICAL_EMBEDDING_API_KEY",  # embedding API key 环境变量名，不写真实密钥。
    "base_url_env": "MEDICAL_EMBEDDING_BASE_URL",  # embedding base URL 环境变量名。
    "model_env": "MEDICAL_EMBEDDING_MODEL",  # embedding model 环境变量名。
    "default_model": "text-embedding-3-small",  # 未配置 model 环境变量时的兜底模型。
    "batch_size": 32,  # 构建知识库时的 embedding batch size。
    "chunk_size": 700,  # 医疗语料切块大小。
    "chunk_overlap": 100,  # 医疗语料切块重叠。
    "persist_directory": str(MEDICAL_VECTOR_DB_DIR),  # 向量库写入目录，禁止随意清空。
    "collection_name": "pubmedqa_clean",  # Chroma collection 名称。
}

"""
定义医疗知识库构建配置；build_knowledge.py --profile medical 会读取这里并写入向量库目录。
"""
MEDICAL_KNOWLEDGE_BUILD_CONFIG = {
    "corpus_path": str(ACTIVE_CORPUS_PATH),  # build_knowledge.py --profile medical 读取的 active 语料。
    "persist_directory": str(MEDICAL_VECTOR_DB_DIR),  # 向量库写入目录，禁止随意清空。
    "collection_name": "pubmedqa_clean",  # Chroma collection 名称。
    "chunk_size": 700,  # 构建知识库时的切块大小。
    "chunk_overlap": 100,  # 构建知识库时的切块重叠。
    "embedding_config": MEDICAL_EMBEDDING_CONFIG,  # 医疗 embedding 配置。
}

"""
定义备用 active retrieval 评测配置；当前主 pipeline 使用 RETRIEVAL_EVAL_CONFIG，这里保留给独立工具。
"""
ACTIVE_RETRIEVAL_EVAL_CONFIG = {
    "corpus_path": str(ACTIVE_CORPUS_PATH),  # 备用工具读取的 active corpus。
    "dataset_path": str(ACTIVE_EVAL_DATASET_PATH),  # 备用工具读取的 active 测试集。
    "output_path": str(MACHINE_OUTPUT_DIR / "retrieval_eval_result.json"),  # 备用 retrieval 输出。
    "report_path": str(REPORT_OUTPUT_DIR / "retrieval_eval_report.md"),  # 备用 retrieval 报告。
    "top_k": 5,  # 备用工具检索 top-k。
    "limit": 30,  # 备用工具默认 smoke 条数。
    "save_output": True,  # 是否保存 JSON 输出。
    "save_markdown": True,  # 是否保存 Markdown 报告。
}
