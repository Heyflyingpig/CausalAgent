import unittest


class StagingReleaseTests(unittest.TestCase):
    def test_rejects_production_identifier_in_manifest(self):
        from scripts.staging_release import validate_manifest

        with self.assertRaisesRegex(ValueError, "production identifier"):
            validate_manifest({"project": "causalagent-production"})

    def test_rejects_production_identifier_in_dsn_before_required_fields(self):
        from scripts.staging_release import validate_manifest

        with self.assertRaisesRegex(ValueError, "production identifier"):
            validate_manifest({"dsn": "mysql://writer@production-db/rag_eval_staging"})
