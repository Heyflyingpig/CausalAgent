"""运行 P3 多模态 RAG smoke，并写出可审计的字段级报告。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from Agent.knowledge_base.multimodal.assets import AssetStore
from Agent.knowledge_base.rag_runtime import RagRuntimeConfig, create_rag_runtime
from Agent.knowledge_base.rag_service import RagService
from app.agent.core import initialize_llm, llm


CASES = (
    ("text", "贝叶斯反演公式中的先验概率和后验概率分别是什么？"),
    ("table", "表 6.1 中，综合数据与按性别分层的数据为什么会给出相反的用药结论？"),
    ("image_ocr", "图 1.7 中，疫苗接种通过哪两条因果路径影响死亡？"),
    (
        "cross_page",
        "结合原子干预 do(X=x) 的结构方程替换与反事实世界的最小修改，说明两者共享的建模原则。",
    ),
    ("unanswerable", "这两本 Pearl 文献是否给出了 2026 年世界杯冠军？"),
)


def _evidence_fields(evidence: dict[str, Any], assets: AssetStore) -> dict[str, Any]:
    """仅保留 P3 要求核验的证据定位字段。"""
    asset_uri = str(evidence.get("asset_uri") or "")
    return {
        "document_id": evidence.get("doc_id"),
        "page_number": evidence.get("page"),
        "content_kind": evidence.get("content_kind"),
        "modality": evidence.get("modality"),
        "asset_uri": asset_uri or None,
        "asset_available": assets.exists(asset_uri) if asset_uri else False,
    }


def main() -> int:
    """使用真实 active pointer 运行五类查询并保存 JSON 报告。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not initialize_llm():
        raise RuntimeError("LLM 初始化失败，无法验证最终回答")
    runtime = create_rag_runtime(RagRuntimeConfig.from_environment(), llm)
    service = RagService(runtime)
    assets = AssetStore(Path("Agent/knowledge_base/multimodal_assets"))
    cases = []
    for case_type, question in CASES:
        result = service.get_response([question])
        question_result = result["questions"][0] if result.get("questions") else {}
        evidence = question_result.get("retrieved_docs", [])
        cases.append(
            {
                "case_type": case_type,
                "question": question,
                "status": question_result.get("status"),
                "answer": question_result.get("answer"),
                "citations": question_result.get("citations", []),
                "evidence_count": len(evidence),
                "evidence": [_evidence_fields(item, assets) for item in evidence],
            }
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "service_type": type(service).__name__,
            "release_id": runtime.config.release_id,
            "collection_name": runtime.config.collection_name,
            "chunk_count": runtime.chunk_count,
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
