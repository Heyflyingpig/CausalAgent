"""Job execution 历史租约兼容修复的安全边界测试。"""

from pathlib import Path
from unittest import TestCase

from Database.job_execution_upgrade_repair import (
    MIGRATION_COLUMNS,
    RepairRefusedError,
    UpgradeCompatibilityReport,
    _mapping_value,
    _validate_apply,
)


class JobExecutionUpgradeRepairTests(TestCase):
    def test_information_schema_keys_are_read_case_insensitively(self):
        self.assertEqual(
            _mapping_value({"TABLE_NAME": "analysis_jobs"}, "table_name"),
            "analysis_jobs",
        )

    def test_report_blocks_stale_non_running_leases_before_migration(self):
        report = UpgradeCompatibilityReport(
            revisions=("a1b2c3d4e5f6",),
            analysis_jobs_exists=True,
            migration_columns=(),
            running_count=0,
            repairable_count=8,
        )

        self.assertTrue(report.applicable)
        self.assertTrue(report.blocked)
        self.assertFalse(report.partial_schema)

    def test_report_treats_complete_target_columns_as_already_migrated(self):
        report = UpgradeCompatibilityReport(
            revisions=("b2c3d4e5f6a7",),
            analysis_jobs_exists=True,
            migration_columns=tuple(sorted(MIGRATION_COLUMNS)),
            running_count=0,
            repairable_count=0,
        )

        self.assertTrue(report.migration_applied)
        self.assertFalse(report.applicable)
        self.assertFalse(report.blocked)

    def test_apply_requires_matching_revision_count_and_no_running_jobs(self):
        clean = UpgradeCompatibilityReport(
            revisions=("a1b2c3d4e5f6",),
            analysis_jobs_exists=True,
            migration_columns=(),
            running_count=0,
            repairable_count=8,
        )
        _validate_apply(
            clean,
            confirmed_revision="a1b2c3d4e5f6",
            expected_count=8,
        )

        with self.assertRaisesRegex(RepairRefusedError, "revision_mismatch"):
            _validate_apply(
                clean,
                confirmed_revision="wrong",
                expected_count=8,
            )
        with self.assertRaisesRegex(RepairRefusedError, "candidate_count_mismatch"):
            _validate_apply(
                clean,
                confirmed_revision="a1b2c3d4e5f6",
                expected_count=7,
            )

        running = UpgradeCompatibilityReport(
            revisions=("a1b2c3d4e5f6",),
            analysis_jobs_exists=True,
            migration_columns=(),
            running_count=1,
            repairable_count=8,
        )
        with self.assertRaisesRegex(RepairRefusedError, "running_jobs_present"):
            _validate_apply(
                running,
                confirmed_revision="a1b2c3d4e5f6",
                expected_count=8,
            )

    def test_repair_sql_only_clears_legacy_lease_ownership(self):
        source = Path("Database/job_execution_upgrade_repair.py").read_text(
            encoding="utf-8"
        )
        update = source.split("UPDATE analysis_jobs", 1)[1].split('"""', 1)[0]

        self.assertIn("SET worker_id = NULL", update)
        self.assertIn("locked_at = NULL", update)
        self.assertNotIn("heartbeat_at = NULL", update)
        self.assertNotIn("DELETE", update)
