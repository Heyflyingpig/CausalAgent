"""在显式标记的隔离数据库上演练评测持久队列,不调用模型或摄取器。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def require_drill_environment() -> None:
    if os.getenv("RAG_EVAL_DRILL") != "true":
        raise RuntimeError("RAG_EVAL_DRILL=true is required for the MySQL queue drill")


def run_drill() -> dict:
    require_drill_environment()
    from app.db import get_write_connection
    from app.rag_eval import job_service

    prefix = f"drill_{uuid.uuid4().hex}_"
    limits = job_service.job_limits()
    expected_running = sum(limits.values())
    run_ids: list[str] = []
    try:
        for kind, limit in limits.items():
            for position in range(limit + 1):
                run_id = f"{prefix}{kind}_{position}"
                job_service.enqueue_job(run_id, kind, {"drill": True})
                run_ids.append(run_id)

        def claim(index: int):
            return job_service.claim_next_job(f"mysql-drill-{index}")

        with ThreadPoolExecutor(max_workers=min(len(run_ids), 5)) as executor:
            claimed = [job for job in executor.map(claim, range(len(run_ids))) if job]
        by_kind = Counter(str(job["job_kind"]) for job in claimed)
        if len(claimed) != expected_running or dict(by_kind) != limits:
            raise RuntimeError(f"concurrency gate failed: claimed={len(claimed)} counts={dict(by_kind)} limits={limits}")

        snapshot = job_service.get_capacity_snapshot()
        if snapshot["running_total"] != expected_running:
            raise RuntimeError(f"capacity snapshot mismatch: {snapshot}")

        stale_run = claimed[0]["run_id"]
        with get_write_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE rag_eval_jobs SET heartbeat_at = UTC_TIMESTAMP(6) - INTERVAL 31 SECOND WHERE run_id = %s",
                (stale_run,),
            )
            conn.commit()
        reconciled = job_service.reconcile_stale_jobs()
        if stale_run not in {job["run_id"] for job in reconciled}:
            raise RuntimeError("stale-job recovery did not fence the injected drill job")

        return {
            "status": "pass",
            "prefix": prefix,
            "limits": limits,
            "claimed_total": len(claimed),
            "claimed_by_kind": dict(by_kind),
            "capacity": snapshot,
            "stale_reconciled_run_id": stale_run,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        with get_write_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rag_eval_jobs WHERE run_id LIKE %s", (f"{prefix}%",))
            conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing drill report: {args.output}")
    result = run_drill()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
