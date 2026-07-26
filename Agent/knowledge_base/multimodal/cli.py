"""开发维护者使用的离线多模态知识库 CLI。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .benchmark import audit_omnidocbench_subset, evaluate_omnidocbench_staged_index
from .omnidocbench_export import export_omnidocbench_official_inputs
from .pipeline import MultimodalKnowledgeBaseMaintenance


def build_parser() -> argparse.ArgumentParser:
    """构造与实施方案一致的子命令接口。"""
    parser = argparse.ArgumentParser(prog="multimodal-knowledge-base")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "ingest", "run"):
        sub = commands.add_parser(name); sub.add_argument("--source", action="append", required=True)
    for name in ("ingest", "run"):
        commands.choices[name].add_argument("--allow-remote-data", action="store_true")
        commands.choices[name].add_argument("--max-images", type=int, default=12)
        commands.choices[name].add_argument("--retry-failed", action="store_true")
        commands.choices[name].add_argument("--retry-generation", type=int, default=0)
    commands.choices["run"].add_argument("--timeout-seconds", type=int)
    commands.choices["run"].add_argument("--cancel-file")
    for name in ("evaluate", "publish", "status", "rollback"):
        sub = commands.add_parser(name); sub.add_argument("--index-version", required=name != "status")
    benchmark_audit = commands.add_parser("omnidocbench-audit")
    benchmark_audit.add_argument("--root", required=True)
    benchmark_eval = commands.add_parser("omnidocbench-evaluate")
    benchmark_eval.add_argument("--root", required=True); benchmark_eval.add_argument("--index-version", required=True)
    benchmark_eval.add_argument("--asset-root", required=True); benchmark_eval.add_argument("--index-root", required=True); benchmark_eval.add_argument("--output-dir", required=True)
    benchmark_export = commands.add_parser("omnidocbench-export-official")
    benchmark_export.add_argument("--root", required=True); benchmark_export.add_argument("--output-dir", required=True); benchmark_export.add_argument("--selection-manifest")
    return parser


def main() -> int:
    """执行一个维护命令并以 JSON 输出可审计结果。"""
    load_dotenv()
    args = build_parser().parse_args(); service = MultimodalKnowledgeBaseMaintenance()
    if args.command == "omnidocbench-audit": result = audit_omnidocbench_subset(Path(args.root))
    elif args.command == "omnidocbench-export-official": result = export_omnidocbench_official_inputs(Path(args.root), Path(args.output_dir), selection_manifest=Path(args.selection_manifest) if args.selection_manifest else None)
    elif args.command == "omnidocbench-evaluate":
        result = evaluate_omnidocbench_staged_index(Path(args.root), Path(args.index_root), args.index_version, Path(args.asset_root), Path(args.output_dir))
        (Path(args.index_root) / args.index_version / "omnidocbench_eval.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    elif args.command == "inspect": result = service.inspect(args.source)
    elif args.command == "ingest": result = service.ingest(args.source, allow_remote_data=args.allow_remote_data, max_images=args.max_images, retry_failed=args.retry_failed, retry_generation=args.retry_generation)
    elif args.command == "run": result = service.run(args.source, allow_remote_data=args.allow_remote_data, max_images=args.max_images, retry_failed=args.retry_failed, retry_generation=args.retry_generation, timeout_seconds=args.timeout_seconds, cancel_check=(lambda: Path(args.cancel_file).exists()) if args.cancel_file else None)
    elif args.command == "evaluate": result = service.evaluate(args.index_version)
    elif args.command == "publish": result = service.publish(args.index_version)
    elif args.command == "rollback": result = service.rollback(args.index_version)
    else: result = service.status(args.index_version)
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
