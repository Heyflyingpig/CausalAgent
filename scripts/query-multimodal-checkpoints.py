"""只读查询多模态候选的 SQLite checkpoint。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """构造不会修改候选目录的查询参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-db", required=True, type=Path)
    parser.add_argument("--document-id")
    parser.add_argument("--page-number", type=int)
    parser.add_argument("--include-units", action="store_true")
    parser.add_argument("--local-parse", action="store_true")
    return parser


def main() -> int:
    """输出 checkpoint 概览或单页记录，不写入 SQLite 文件。"""
    args = build_parser().parse_args()
    path = args.checkpoint_db.resolve()
    if not path.is_file():
        raise SystemExit(f"checkpoint database does not exist: {path}")
    if bool(args.document_id) != (args.page_number is not None):
        raise SystemExit("--document-id and --page-number must be provided together")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        if args.document_id is None:
            payload = {
                "checkpoint_db": str(path),
                "page_checkpoints": connection.execute("SELECT COUNT(*) FROM page_checkpoints").fetchone()[0],
                "page_units": connection.execute("SELECT COUNT(*) FROM page_units").fetchone()[0],
                "local_parse_checkpoints": connection.execute("SELECT COUNT(*) FROM local_parse_checkpoints").fetchone()[0],
            }
        else:
            table = "local_parse_checkpoints" if args.local_parse else "page_checkpoints"
            row = connection.execute(
                f"SELECT checkpoint_json FROM {table} WHERE document_id = ? AND page_number = ?",
                (args.document_id, args.page_number),
            ).fetchone()
            if row is None:
                raise SystemExit("checkpoint page does not exist")
            payload = json.loads(row[0])
            if args.include_units and not args.local_parse:
                payload["units"] = [
                    json.loads(unit_row[0])
                    for unit_row in connection.execute(
                        "SELECT unit_json FROM page_units WHERE document_id = ? AND page_number = ? ORDER BY unit_index",
                        (args.document_id, args.page_number),
                    )
                ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
