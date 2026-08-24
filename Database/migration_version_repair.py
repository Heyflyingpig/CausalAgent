"""安全修复历史重复 Alembic revision ID 的版本表记录。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


LEGACY_FILE_RECOVERY_REVISION = "a1b2c3d4e5f6"
FILE_RECOVERY_REVISION = "j0a1b2c3d4e5"
LEGACY_EXECUTION_RELEASE_REVISION = "b2c3d4e5f6a7"
EXECUTION_RELEASE_REVISION = "k0b2c3d4e5f6"
_FILE_RECOVERY_TABLES = {"file_objects", "user_files", "analysis_job_inputs"}
_EXECUTION_RELEASE_COLUMNS = {
    "execution_state",
    "execution_released_at",
    "execution_release_reason",
}


class LegacyMigrationVersionError(RuntimeError):
    """历史重复 revision 的物理 schema 无法被唯一识别。"""


def repair_legacy_revision_ids(connection: Any) -> list[str]:
    """按物理 schema 将旧 Agent 分支的重复 revision 映射为唯一 ID。

    旧 RAG 分支与 Agent 分支曾意外共用两个 revision ID。只有 version table
    命中旧 ID 且表结构能唯一证明它属于 Agent 分支时才更新；任何混合或缺失
    证据都会 fail closed，交由人工审计后再迁移。
    """
    cursor = connection.cursor(dictionary=True)
    try:
        tables = _table_names(cursor)
        if "alembic_version" not in tables:
            return []
        cursor.execute("SELECT version_num FROM alembic_version FOR UPDATE")
        revisions = {_value(row, "version_num") for row in cursor.fetchall()}
        replacements: dict[str, str] = {}
        if LEGACY_FILE_RECOVERY_REVISION in revisions:
            replacements.update(_file_recovery_replacement(tables))
        if LEGACY_EXECUTION_RELEASE_REVISION in revisions:
            replacements.update(_execution_release_replacement(cursor, tables))
        for old_revision, new_revision in replacements.items():
            cursor.execute(
                "UPDATE alembic_version SET version_num = %s WHERE version_num = %s",
                (new_revision, old_revision),
            )
        if replacements:
            connection.commit()
        return [f"{old}->{new}" for old, new in replacements.items()]
    finally:
        cursor.close()


def _table_names(cursor: Any) -> set[str]:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name IN ('alembic_version', 'rag_eval_profiles', 'rag_eval_jobs',
                             'file_objects', 'user_files', 'analysis_job_inputs',
                             'analysis_jobs')
        """
    )
    return {_value(row, "table_name") for row in cursor.fetchall()}


def _file_recovery_replacement(tables: set[str]) -> dict[str, str]:
    agent_schema = _FILE_RECOVERY_TABLES <= tables
    rag_schema = "rag_eval_profiles" in tables
    if agent_schema and not rag_schema:
        return {LEGACY_FILE_RECOVERY_REVISION: FILE_RECOVERY_REVISION}
    if rag_schema and not agent_schema:
        return {}
    raise LegacyMigrationVersionError(
        "cannot identify legacy revision a1b2c3d4e5f6 from the current schema"
    )


def _execution_release_replacement(cursor: Any, tables: set[str]) -> dict[str, str]:
    agent_schema = _FILE_RECOVERY_TABLES <= tables and _execution_release_columns(cursor)
    rag_schema = "rag_eval_jobs" in tables
    if agent_schema and not rag_schema:
        return {LEGACY_EXECUTION_RELEASE_REVISION: EXECUTION_RELEASE_REVISION}
    if rag_schema and not agent_schema:
        return {}
    raise LegacyMigrationVersionError(
        "cannot identify legacy revision b2c3d4e5f6a7 from the current schema"
    )


def _execution_release_columns(cursor: Any) -> bool:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'analysis_jobs'
          AND column_name IN ('execution_state', 'execution_released_at',
                              'execution_release_reason')
        """
    )
    return {_value(row, "column_name") for row in cursor.fetchall()} == _EXECUTION_RELEASE_COLUMNS


def _value(row: Mapping[str, Any] | tuple[Any, ...], key: str) -> str:
    if isinstance(row, Mapping):
        normalized_key = key.casefold()
        for row_key, value in row.items():
            if str(row_key).casefold() == normalized_key:
                return str(value)
        raise KeyError(key)
    return str(row[0])
