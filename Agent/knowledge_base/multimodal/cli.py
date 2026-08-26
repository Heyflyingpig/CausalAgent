"""开发维护者使用的离线多模态知识库 CLI。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .pipeline import MultimodalKnowledgeBaseMaintenance
from .production import production_source_paths
from observability.cli import write_cli_output


def build_parser() -> argparse.ArgumentParser:
    """构造与实施方案一致的子命令接口。"""
    parser = argparse.ArgumentParser(prog="multimodal-knowledge-base")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "prepare-outbound-manifest", "r2-smoke", "ingest", "run"):
        sub = commands.add_parser(name); sub.add_argument("--source", action="append")
    prepare = commands.choices["prepare-outbound-manifest"]
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--max-images", type=int)
    prepare.add_argument("--max-pages", type=int)
    prepare.add_argument("--all-production-pages", action="store_true")
    prepare.add_argument("--checkpoint-dir")
    prepare.add_argument("--authorize-source", action="append", dest="authorized_source_ids")
    smoke = commands.choices["r2-smoke"]
    smoke.add_argument("--outbound-manifest", required=True)
    smoke.add_argument("--output", required=True)
    smoke.add_argument("--authorize-source", action="append", dest="authorized_source_ids")
    for name in ("ingest", "run"):
        commands.choices[name].add_argument("--allow-remote-data", action="store_true")
        commands.choices[name].add_argument("--authorize-source", action="append", dest="authorized_source_ids")
        commands.choices[name].add_argument("--max-images", type=int)
        commands.choices[name].add_argument("--outbound-manifest")
        commands.choices[name].add_argument("--retry-failed", action="store_true")
        commands.choices[name].add_argument("--retry-generation", type=int, choices=range(3), default=0)
        commands.choices[name].add_argument("--retry-from-index-version")
        commands.choices[name].add_argument("--reuse-local-checkpoints-from")
    commands.choices["run"].add_argument("--timeout-seconds", type=int)
    commands.choices["run"].add_argument("--cancel-file")
    commands.choices["run"].add_argument("--publish", action="store_true")
    for name in ("evaluate", "publish", "status", "rollback"):
        sub = commands.add_parser(name); sub.add_argument("--index-version", required=name != "status")
    return parser


def main() -> int:
    """执行一个维护命令并以 JSON 输出可审计结果。"""
    load_dotenv()
    args = build_parser().parse_args(); service = MultimodalKnowledgeBaseMaintenance()
    if args.command == "inspect": result = service.inspect(args.source or [str(path) for path in production_source_paths()])
    elif args.command == "prepare-outbound-manifest": result = service.prepare_outbound_manifest(args.source or [str(path) for path in production_source_paths()], args.output, max_images=args.max_images, max_pages=args.max_pages, all_production_pages=args.all_production_pages, checkpoint_dir=args.checkpoint_dir, authorized_source_ids=args.authorized_source_ids)
    elif args.command == "r2-smoke": result = service.run_r2_smoke(args.source or [str(path) for path in production_source_paths()], args.outbound_manifest, args.output, authorized_source_ids=args.authorized_source_ids)
    elif args.command == "ingest": result = service.ingest(args.source or [str(path) for path in production_source_paths()], allow_remote_data=args.allow_remote_data, authorized_source_ids=args.authorized_source_ids, max_images=args.max_images, retry_failed=args.retry_failed, retry_generation=args.retry_generation, retry_from_index_version=args.retry_from_index_version, reuse_local_from_index_version=args.reuse_local_checkpoints_from, outbound_manifest=args.outbound_manifest)
    elif args.command == "run": result = service.run(args.source or [str(path) for path in production_source_paths()], allow_remote_data=args.allow_remote_data, authorized_source_ids=args.authorized_source_ids, max_images=args.max_images, retry_failed=args.retry_failed, retry_generation=args.retry_generation, retry_from_index_version=args.retry_from_index_version, reuse_local_from_index_version=args.reuse_local_checkpoints_from, outbound_manifest=args.outbound_manifest, timeout_seconds=args.timeout_seconds, cancel_check=(lambda: Path(args.cancel_file).exists()) if args.cancel_file else None, publish_on_pass=args.publish)
    elif args.command == "evaluate": result = service.evaluate(args.index_version)
    elif args.command == "publish": result = service.publish(args.index_version)
    elif args.command == "rollback": result = service.rollback(args.index_version)
    else: result = service.status(args.index_version)
    write_cli_output(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
