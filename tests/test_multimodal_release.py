"""多模态隔离 staged 产物晋级正式候选目录的契约测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from Agent.knowledge_base.multimodal.pipeline import MultimodalKnowledgeBaseMaintenance


class MultimodalReleaseTests(unittest.TestCase):
    def test_promote_staged_copies_index_and_assets_without_switching_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged_index_root = root / "staged" / "indexes"
            staged_asset_root = root / "staged" / "assets"
            formal_index_root = root / "formal" / "indexes"
            formal_asset_root = root / "formal" / "assets"
            version_dir = staged_index_root / "mm_release_test"
            version_dir.mkdir(parents=True)
            (version_dir / "manifest.json").write_text(json.dumps({"index_version": "mm_release_test"}), encoding="utf-8")
            (version_dir / "units.jsonl").write_text("unit\n", encoding="utf-8")
            asset = staged_asset_root / "doc" / "images" / "page.png"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"asset")

            maintenance = MultimodalKnowledgeBaseMaintenance(
                asset_root=formal_asset_root,
                index_root=formal_index_root,
                active_config=root / "formal" / "active_index.json",
            )
            result = maintenance.promote_staged(
                source_index_root=staged_index_root,
                source_asset_root=staged_asset_root,
                index_version="mm_release_test",
            )

            self.assertEqual(result["status"], "promoted")
            self.assertTrue((formal_index_root / "mm_release_test" / "manifest.json").is_file())
            self.assertEqual((formal_asset_root / "doc" / "images" / "page.png").read_bytes(), b"asset")
            self.assertIsNone(maintenance.registry.read())

            reused = maintenance.promote_staged(
                source_index_root=staged_index_root,
                source_asset_root=staged_asset_root,
                index_version="mm_release_test",
            )
            self.assertEqual(reused["status"], "reused")


if __name__ == "__main__":
    unittest.main()
