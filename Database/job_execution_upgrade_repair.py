"""旧库 Job 执行租约兼容检查与显式修复工具。

``b2c3d4e5f6a7`` 会为 ``analysis_jobs`` 增加执行状态约束。旧版本可能在
非运行任务上遗留 ``worker_id`` / ``locked_at``，导致该历史迁移无法落地。
本模块默认只读；数据修复必须同时确认数据库、当前 revision 和预期条数。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Mapping


TARGET_REVISION = "b2c3d4e5f6a7"
MIGRATION_COLUMNS = frozenset(
    {
        "execution_state",
        "execution_released_at",
        "execution_release_reason",
    }
)
MAX_REPAIR_ROWS = 10_000


@dataclass(frozen=True)
class UpgradeCompatibilityReport:
    """不包含任务 ID、worker 标识或数据库连接信息的兼容性摘要。"""

    revisions: tuple[str, ...]
    analysis_jobs_exists: bool
    migration_columns: tuple[str, ...]
    running_count: int
    repairable_count: int

    @property
    def partial_schema(self) -> bool:
        present = set(self.migration_columns)
        return bool(present) and present != MIGRATION_COLUMNS

    @property
    def migration_applied(self) -> bool:
        return set(self.migration_columns) == MIGRATION_COLUMNS

    @property
    def applicable(self) -> bool:
        return self.analysis_jobs_exists and not self.migration_applied

    @property
    def blocked(self) -> bool:
        return self.partial_schema or (
            self.applicable
            and (self.running_count > 0 or self.repairable_count > 0)
        )

    def to_safe_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.update(
            {
                "target_revision": TARGET_REVISION,
                "partial_schema": self.partial_schema,
                "migration_applied": self.migration_applied,
                "applicable": self.applicable,
                "blocked": self.blocked,
            }
        )
        return result


class JobExecutionUpgradeBlockedError(RuntimeError):
    """迁移前置条件不满足；异常正文只使用固定安全消息。"""

    def __init__(self, report: UpgradeCompatibilityReport):
        super().__init__(
            "Job execution migration precondition failed; "
            "run the explicit compatibility repair command"
        )
        self.report = report


class RepairRefusedError(RuntimeError):
    """显式修复参数或数据库状态不满足安全边界。"""

    def __init__(self, reason_code: str, report: UpgradeCompatibilityReport):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.report = report


def _mapping_value(row: Mapping[str, Any] | None, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if key in row:
        return row[key]
    lowered = key.lower()
    for candidate, value in row.items():
        if str(candidate).lower() == lowered:
            return value
    return default


def inspect_upgrade_compatibility(
    connection: Any,
    *,
    lock_candidates: bool = False,
) -> UpgradeCompatibilityReport:
    """检查目标迁移前置条件；apply 时额外锁定候选 Job 行。"""

    cursor = connection.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name IN ('alembic_version', 'analysis_jobs')
        """
    )
    tables = {
        str(_mapping_value(row, "table_name"))
        for row in cursor.fetchall()
        if _mapping_value(row, "table_name")
    }

    revisions: tuple[str, ...] = ()
    if "alembic_version" in tables:
        cursor.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
        revisions = tuple(
            str(_mapping_value(row, "version_num"))
            for row in cursor.fetchall()
            if _mapping_value(row, "version_num")
        )

    if "analysis_jobs" not in tables:
        return UpgradeCompatibilityReport(revisions, False, (), 0, 0)

    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'analysis_jobs'
          AND column_name IN (
              'execution_state',
              'execution_released_at',
              'execution_release_reason'
          )
        ORDER BY column_name
        """
    )
    migration_columns = tuple(
        str(_mapping_value(row, "column_name"))
        for row in cursor.fetchall()
        if _mapping_value(row, "column_name")
    )
    if set(migration_columns) == MIGRATION_COLUMNS:
        return UpgradeCompatibilityReport(
            revisions,
            True,
            migration_columns,
            0,
            0,
        )
    if migration_columns:
        return UpgradeCompatibilityReport(
            revisions,
            True,
            migration_columns,
            0,
            0,
        )

    cursor.execute(
        """
        SELECT
            COALESCE(SUM(status = 'running'), 0) AS running_count,
            COALESCE(SUM(
                status <> 'running'
                AND (worker_id IS NOT NULL OR locked_at IS NOT NULL)
            ), 0) AS repairable_count
        FROM analysis_jobs
        """
    )
    counts = cursor.fetchone() or {}
    report = UpgradeCompatibilityReport(
        revisions,
        True,
        (),
        int(_mapping_value(counts, "running_count", 0) or 0),
        int(_mapping_value(counts, "repairable_count", 0) or 0),
    )

    if lock_candidates and (report.running_count or report.repairable_count):
        cursor.execute(
            f"""
            SELECT id
            FROM analysis_jobs
            WHERE status = 'running'
               OR (status <> 'running'
                   AND (worker_id IS NOT NULL OR locked_at IS NOT NULL))
            ORDER BY id
            LIMIT {MAX_REPAIR_ROWS + 1}
            FOR UPDATE
            """
        )
        locked_rows = cursor.fetchall()
        if len(locked_rows) != report.running_count + report.repairable_count:
            raise RepairRefusedError("candidate_set_changed", report)

    return report


def _connect(mysql_config: Mapping[str, Any]) -> Any:
    import mysql.connector

    return mysql.connector.connect(**dict(mysql_config))


def check_upgrade_compatibility(
    mysql_config: Mapping[str, Any],
    *,
    connect: Callable[[Mapping[str, Any]], Any] = _connect,
) -> UpgradeCompatibilityReport:
    """供 bootstrap 调用的只读迁移前检查。"""

    connection = connect(mysql_config)
    try:
        report = inspect_upgrade_compatibility(connection)
    finally:
        connection.close()
    if report.blocked:
        raise JobExecutionUpgradeBlockedError(report)
    return report


def _validate_apply(
    report: UpgradeCompatibilityReport,
    *,
    confirmed_revision: str,
    expected_count: int,
) -> None:
    if report.partial_schema:
        raise RepairRefusedError("partial_migration_schema", report)
    if not report.applicable:
        raise RepairRefusedError("repair_not_applicable", report)
    if len(report.revisions) != 1 or report.revisions[0] != confirmed_revision:
        raise RepairRefusedError("revision_mismatch", report)
    if report.running_count:
        raise RepairRefusedError("running_jobs_present", report)
    if report.repairable_count > MAX_REPAIR_ROWS:
        raise RepairRefusedError("repair_limit_exceeded", report)
    if report.repairable_count != expected_count:
        raise RepairRefusedError("candidate_count_mismatch", report)


def apply_repair(
    connection: Any,
    *,
    confirmed_revision: str,
    expected_count: int,
) -> dict[str, Any]:
    """在单个事务中锁定并清除非运行 Job 的旧执行占用字段。"""

    try:
        connection.start_transaction(isolation_level="SERIALIZABLE")
        report = inspect_upgrade_compatibility(connection, lock_candidates=True)
        _validate_apply(
            report,
            confirmed_revision=confirmed_revision,
            expected_count=expected_count,
        )
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE analysis_jobs
            SET worker_id = NULL,
                locked_at = NULL
            WHERE status <> 'running'
              AND (worker_id IS NOT NULL OR locked_at IS NOT NULL)
            """
        )
        updated_count = int(cursor.rowcount)
        if updated_count != expected_count:
            raise RepairRefusedError("updated_count_mismatch", report)

        verified = inspect_upgrade_compatibility(connection)
        if verified.running_count or verified.repairable_count:
            raise RepairRefusedError("post_repair_verification_failed", verified)
        connection.commit()
        return {
            "mode": "apply",
            "updated_count": updated_count,
            "current_revision": confirmed_revision,
            "target_revision": TARGET_REVISION,
        }
    except Exception:
        connection.rollback()
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="预览或修复 b2c3d4e5f6a7 前的旧 Job 执行占用字段",
    )
    parser.add_argument("--apply", action="store_true", help="执行修复；默认只读")
    parser.add_argument("--confirm-database", default="")
    parser.add_argument("--confirm-revision", default="")
    parser.add_argument("--expected-count", type=int)
    args = parser.parse_args()
    if args.expected_count is not None and args.expected_count < 0:
        parser.error("--expected-count 不能小于 0")
    return args


def _safe_error(reason_code: str, report: UpgradeCompatibilityReport | None = None) -> None:
    payload: dict[str, Any] = {"mode": "error", "reason_code": reason_code}
    if report is not None:
        payload["report"] = report.to_safe_dict()
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def main() -> int:
    """默认输出安全 dry-run 摘要；apply 需要三项显式确认。"""

    args = _parse_args()
    try:
        from Database.database_init import DatabaseBootstrap

        bootstrap = DatabaseBootstrap()
        connection = _connect(bootstrap.mysql_config)
        try:
            if not args.apply:
                report = inspect_upgrade_compatibility(connection)
                print(
                    json.dumps(
                        {"mode": "dry-run", **report.to_safe_dict()},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                return 0

            if args.confirm_database != str(bootstrap.mysql_config["database"]):
                _safe_error("database_confirmation_mismatch")
                return 2
            if not args.confirm_revision or args.expected_count is None:
                _safe_error("apply_confirmation_incomplete")
                return 2
            result = apply_repair(
                connection,
                confirmed_revision=args.confirm_revision,
                expected_count=args.expected_count,
            )
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 0
        finally:
            connection.close()
    except RepairRefusedError as exc:
        _safe_error(exc.reason_code, exc.report)
        return 2
    except Exception:
        _safe_error("database_unavailable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
