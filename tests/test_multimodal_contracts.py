"""多模态知识库的无网络契约与隔离行为测试。"""

from __future__ import annotations

import tempfile
import unittest
import os
import json
import threading
import time
from unittest.mock import MagicMock, patch
from pathlib import Path
from unittest.mock import patch

from Agent.knowledge_base.multimodal.assets import AssetStore
from Agent.knowledge_base.multimodal.benchmark import audit_omnidocbench_subset, evaluate_omnidocbench_staged_index
from Agent.knowledge_base.multimodal.omnidocbench_export import export_omnidocbench_official_inputs
from Agent.knowledge_base.multimodal.contracts import BoundingBox, IngestionIssue, IssueSeverity, KnowledgeUnit, UnitStatus, VisionAnalysis, render_retrieval_text, sha256_bytes, stable_id
from Agent.knowledge_base.multimodal.pipeline import MultimodalKnowledgeBaseMaintenance
from Agent.knowledge_base.multimodal.parsers import parse_document
from Agent.knowledge_base.multimodal.retrieval import _parent_context
from Agent.knowledge_base.multimodal.retrieval import multimodal_rag_search
from Agent.knowledge_base.rag_runtime import RagRuntimeConfig
from Agent.knowledge_base.multimodal.vision import VisionAnalyzer
from Agent.tool_node.rag_questions import normalize_rag_question_output
from Agent.tool_node.rag_tool_registry import build_rag_tools


class MultimodalContractTests(unittest.TestCase):
    """验证不依赖解析器、模型或远程 API 的核心安全契约。"""

    def test_bbox_rejects_reverse_coordinates(self) -> None:
        """边界框必须使用统一的左上至右下方向。"""
        with self.assertRaises(ValueError):
            BoundingBox(x0=0.8, y0=0.1, x1=0.2, y1=0.9)

    def test_retrieval_text_keeps_uncertain_relation_out_of_directed_relation(self) -> None:
        """不确定箭头只能作为不确定关系输出。"""
        analysis = VisionAnalysis(content_kind="causal_graph", visible_facts=["存在连接线"], uncertain_relations=["A ? B"], confidence=0.5, informative=True)
        text = render_retrieval_text(content_kind="causal_graph", analysis=analysis)
        self.assertIn("A ? B", text)
        self.assertNotIn("A -> B", text)

    def test_asset_store_rejects_escape_and_preserves_existing_asset(self) -> None:
        """资源存储不得允许目录逃逸或同 URI 覆盖。"""
        with tempfile.TemporaryDirectory() as directory:
            store = AssetStore(Path(directory))
            uri = store.put("doc_" + "a" * 64, "figure.png", b"one")
            self.assertEqual(store.read(uri), b"one")
            with self.assertRaises(ValueError):
                store.read("../secret")
            self.assertNotEqual(uri, store.put("doc_" + "a" * 64, "figure.png", b"two"))

    def test_asset_store_shortens_long_names_without_losing_content(self) -> None:
        """Windows 路径限制下，长资源名必须写入可读的确定性 URI。"""
        with tempfile.TemporaryDirectory() as directory:
            store = AssetStore(Path(directory) / ("nested_" * 12))
            name = "page_" + "a" * 180 + ".png"
            uri = store.put("doc_" + "a" * 64, name, b"image")
            self.assertLess(len(Path(uri).name), 80)
            self.assertEqual(store.read(uri), b"image")

    def test_inspect_is_deterministic_and_does_not_create_index(self) -> None:
        """inspect 只产生 manifest，不创建索引或资源目录。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "note.md"; source.write_text("因果图", encoding="utf-8")
            service = MultimodalKnowledgeBaseMaintenance(asset_root=root / "assets", index_root=root / "indexes", active_config=root / "runtime" / "active.json")
            first = service.inspect([str(source)]); second = service.inspect([str(source)])
            self.assertEqual(first["manifest"], second["manifest"])
            self.assertEqual(first["manifest"]["parser"], "docling")
            self.assertIn("parser", first["configuration"])
            self.assertIn("docling_layout_model_available", first["configuration"]["parser"])
            self.assertFalse((root / "indexes").exists())
            self.assertFalse((root / "assets").exists())

    def test_csv_parser_keeps_header_and_row_semantics(self) -> None:
        """CSV 行的检索文本必须包含表头、行号和单元格值。"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data.csv"
            source.write_text("处理,结果\n1,改善\n", encoding="utf-8")
            parsed = parse_document(source, "mineru")
            self.assertEqual(parsed.parser_name, "csv")
            self.assertEqual(parsed.items[0].modality, "table")
            self.assertIn("行：2", parsed.items[0].raw_text)
            self.assertIn("处理：1", parsed.items[0].raw_text)
            self.assertIn("结果：改善", parsed.items[0].raw_text)

    def test_xlsx_parser_keeps_sheet_and_row_semantics(self) -> None:
        """XLSX 行必须包含工作表、行号和对应单元格语义。"""
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data.xlsx"
            workbook = Workbook(); sheet = workbook.active; sheet.title = "实验"; sheet.append(["处理", "结果"]); sheet.append(["干预", "改善"]); workbook.save(source); workbook.close()
            parsed = parse_document(source, "mineru")
            self.assertEqual(parsed.parser_name, "xlsx")
            self.assertIn("工作表：实验", parsed.items[0].raw_text)
            self.assertIn("行：2", parsed.items[0].raw_text)

    def test_docling_pdf_parser_returns_page_scoped_text(self) -> None:
        """本地 Docling artifacts 必须能把 PDF 正文转换为一基页码单元。"""
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.pdf"
            pdf = canvas.Canvas(str(source)); pdf.drawString(72, 720, "Causal inference sample document"); pdf.save()
            parsed = parse_document(source, "mineru")
            self.assertEqual(parsed.parser_name, "docling")
            self.assertTrue(parsed.items, parsed.issues)
            self.assertTrue(any("Causal inference" in item.raw_text for item in parsed.items))
            self.assertTrue(any(item.page_number == 1 for item in parsed.items))

    def test_evaluate_rejects_any_required_source_parse_error(self) -> None:
        """任一默认 required 来源解析失败时不得发布混合成功版本。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); version = "mm_" + "a" * 20; index_dir = root / "indexes" / version; index_dir.mkdir(parents=True)
            unit = KnowledgeUnit(unit_id="unit_" + "a" * 64, document_id="doc_" + "b" * 64, modality="text", content_kind="paragraph", raw_text="正文", retrieval_text="类型：paragraph\n正文", content_hash="c" * 64, parser_name="text", parser_version="1", embedding_provider="huggingface", embedding_model="model", status=UnitStatus.COMPLETED)
            (index_dir / "units.jsonl").write_text(unit.model_dump_json() + "\n", encoding="utf-8")
            issue = IngestionIssue(code="pdf_parse_failed", message="PDF 失败", severity=IssueSeverity.ERROR)
            (index_dir / "issues.jsonl").write_text(issue.model_dump_json() + "\n", encoding="utf-8")
            service = MultimodalKnowledgeBaseMaintenance(asset_root=root / "assets", index_root=root / "indexes", active_config=root / "runtime" / "active.json")
            manifest = {"index_version": version, "embedding": __import__("Agent.knowledge_base.multimodal.index", fromlist=["embedding_fingerprint"]).embedding_fingerprint()}
            (index_dir / "manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")
            with patch("Agent.knowledge_base.multimodal.pipeline.StagedIndex.count", return_value=1):
                result = service.evaluate(version)
            self.assertFalse(result["passed"])
            self.assertIn("required_source_failed", result["failures"])

    def test_evaluate_rejects_missing_original_or_parser_audit_assets(self) -> None:
        """发布门禁必须验证来源和解析器原始产物均可回读。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); version = "mm_" + "a" * 20; index_dir = root / "indexes" / version; index_dir.mkdir(parents=True)
            unit = KnowledgeUnit(unit_id="unit_" + "a" * 64, document_id="doc_" + "b" * 64, modality="text", content_kind="paragraph", raw_text="正文", retrieval_text="类型：paragraph\n正文", content_hash="c" * 64, parser_name="text", parser_version="1", embedding_provider="huggingface", embedding_model="model", status=UnitStatus.COMPLETED)
            (index_dir / "units.jsonl").write_text(unit.model_dump_json() + "\n", encoding="utf-8")
            (index_dir / "issues.jsonl").write_text("", encoding="utf-8")
            service = MultimodalKnowledgeBaseMaintenance(asset_root=root / "assets", index_root=root / "indexes", active_config=root / "runtime" / "active.json")
            manifest = {"index_version": version, "embedding": __import__("Agent.knowledge_base.multimodal.index", fromlist=["embedding_fingerprint"]).embedding_fingerprint(), "sources": [], "documents": [{"document_id": unit.document_id, "content_hash": "c" * 64, "source_asset_uri": "missing/source.txt", "parser_artifact_uris": ["missing/parser.json"]}]}
            (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with patch("Agent.knowledge_base.multimodal.pipeline.StagedIndex.count", return_value=1):
                result = service.evaluate(version)
            self.assertFalse(result["passed"])
            self.assertIn("missing_audit_asset", result["failures"])

    def test_evaluate_rejects_orphaned_standardized_unit(self) -> None:
        """标准化单元必须关联到 manifest 中经哈希验证的原始资料。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); version = "mm_" + "a" * 20; index_dir = root / "indexes" / version; index_dir.mkdir(parents=True)
            unit = KnowledgeUnit(unit_id="unit_" + "a" * 64, document_id="doc_" + "b" * 64, modality="text", content_kind="paragraph", raw_text="正文", retrieval_text="类型：paragraph\n正文", content_hash="c" * 64, parser_name="text", parser_version="1", embedding_provider="huggingface", embedding_model="model", status=UnitStatus.COMPLETED)
            (index_dir / "units.jsonl").write_text(unit.model_dump_json() + "\n", encoding="utf-8")
            (index_dir / "issues.jsonl").write_text("", encoding="utf-8")
            service = MultimodalKnowledgeBaseMaintenance(asset_root=root / "assets", index_root=root / "indexes", active_config=root / "runtime" / "active.json")
            manifest = {"index_version": version, "embedding": __import__("Agent.knowledge_base.multimodal.index", fromlist=["embedding_fingerprint"]).embedding_fingerprint(), "sources": [], "documents": []}
            (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with patch("Agent.knowledge_base.multimodal.pipeline.StagedIndex.count", return_value=1):
                result = service.evaluate(version)
            self.assertFalse(result["passed"])
            self.assertIn("missing_document_audit_chain", result["failures"])

    def test_directory_scan_preserves_relative_paths_for_same_names(self) -> None:
        """同一目录树中的同名文件必须保持不同来源路径。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source_root = root / "sources"
            for folder, text in (("one", "甲"), ("two", "乙")):
                folder_path = source_root / folder; folder_path.mkdir(parents=True)
                (folder_path / "same.md").write_text(text, encoding="utf-8")
            service = MultimodalKnowledgeBaseMaintenance(asset_root=root / "assets", index_root=root / "indexes", active_config=root / "runtime" / "active.json")
            paths = [entry["relative_path"] for entry in service.inspect([str(source_root)])["manifest"]["sources"]]
            self.assertEqual(paths, ["sources/one/same.md", "sources/two/same.md"])

    def test_remote_vision_allowlist_rejects_arbitrary_local_file(self) -> None:
        """显式远程许可也不得扩大到非边界文件。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "private.png"; source.write_bytes(b"not-an-image")
            service = MultimodalKnowledgeBaseMaintenance(asset_root=root / "assets", index_root=root / "indexes", active_config=root / "runtime" / "active.json")
            self.assertFalse(service._remote_resource_allowed(source, None))

    def test_remote_policy_allows_only_fixed_pearl_pages(self) -> None:
        """Pearl 资料必须同时匹配固定文件名和固定页码。"""
        service = MultimodalKnowledgeBaseMaintenance()
        pearl = Path(__file__).resolve().parents[1] / "Agent" / "knowledge_base" / "source" / "Pearl_2009_Causality-mono(1).pdf"
        self.assertTrue(service._remote_resource_allowed(pearl, 1))
        self.assertFalse(service._remote_resource_allowed(pearl, 7))

    def test_omnidocbench_audit_rejects_attribute_drift(self) -> None:
        """固定子集的公开标注属性漂移必须阻止 benchmark 被误用。"""
        with tempfile.TemporaryDirectory() as directory, patch("Agent.knowledge_base.multimodal.benchmark.FIXED_SAMPLES", ({"sample_id": "sample", "relative_path": "images/sample.png", "coverage": "测试", "attributes": {"layout": "double_column"}, "required_categories": ("table",)},)):
            root = Path(directory); (root / "images").mkdir()
            (root / "images" / "sample.png").write_bytes(b"image")
            payload = [{"page_info": {"image_path": "sample.png", "page_attribute": {"layout": "single_column"}}, "layout_dets": []}]
            (root / "OmniDocBench.json").write_text(json.dumps(payload), encoding="utf-8")
            result = audit_omnidocbench_subset(root)
            self.assertFalse(result["passed"])
            self.assertIn("sample:annotation_attribute_mismatch", result["failures"])

    def test_omnidocbench_evaluation_records_successful_enriched_retrieval(self) -> None:
        """公开 OCR probe 命中已增强单元时应计为通过，并写出报告。"""
        with tempfile.TemporaryDirectory() as directory, patch("Agent.knowledge_base.multimodal.benchmark.FIXED_SAMPLES", ({"sample_id": "sample", "relative_path": "images/sample.png", "coverage": "测试", "attributes": {"layout": "single_column"}, "required_categories": ("text_block",)},)):
            root = Path(directory) / "dataset"; (root / "images").mkdir(parents=True)
            content = b"image"; (root / "images" / "sample.png").write_bytes(content)
            annotation = [{"page_info": {"image_path": "sample.png", "page_attribute": {"layout": "single_column"}}, "layout_dets": [{"category_type": "text_block", "text": "abcdefgh retrieval probe"}]}]
            (root / "OmniDocBench.json").write_text(json.dumps(annotation), encoding="utf-8")
            index_version = "mm_" + "a" * 20; index_dir = root / "indexes" / index_version; index_dir.mkdir(parents=True)
            document_id = stable_id("doc", {"path": "images/sample.png", "content_hash": sha256_bytes(content)})
            unit_id = "unit_" + "a" * 64; asset_root = root / "assets"; store = AssetStore(asset_root); asset_uri = store.put(document_id, "sample.png", content)
            manifest = {"documents": [{"document_id": document_id, "relative_path": "images/sample.png"}]}
            unit = {"unit_id": unit_id, "document_id": document_id, "page_number": None, "modality": "image", "content_kind": "image", "raw_text": "", "asset_uri": asset_uri, "vision_model": "mock", "retrieval_text": "OCR：abcdefgh retrieval probe"}
            (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (index_dir / "units.jsonl").write_text(json.dumps(unit) + "\n", encoding="utf-8")
            hit = type("Document", (), {"metadata": {"unit_id": unit_id}})()
            database = MagicMock(); database.similarity_search.return_value = [hit]
            with patch("Agent.knowledge_base.multimodal.benchmark._embeddings", return_value=MagicMock()), patch("Agent.knowledge_base.multimodal.benchmark.Chroma", return_value=database):
                result = evaluate_omnidocbench_staged_index(root, root / "indexes", index_version, asset_root, root / "reports")
            self.assertEqual(result["passed_cases"], 1)
            self.assertEqual(result["failed_cases"], 0)
            self.assertTrue((root / "reports" / "omnidocbench_bad_cases.md").exists())

    def test_omnidocbench_official_export_keeps_fixed_names_and_gt(self) -> None:
        """官方评测导出必须只包含固定页面及其同名 Markdown 预测。"""
        with tempfile.TemporaryDirectory() as directory, patch("Agent.knowledge_base.multimodal.benchmark.FIXED_SAMPLES", ({"sample_id": "sample", "relative_path": "images/sample.png", "coverage": "测试", "attributes": {"layout": "single_column"}, "required_categories": ("text_block",)},)), patch("Agent.knowledge_base.multimodal.omnidocbench_export.FIXED_SAMPLES", ({"sample_id": "sample", "relative_path": "images/sample.png"},)):
            root = Path(directory) / "dataset"; (root / "images").mkdir(parents=True)
            (root / "images" / "sample.png").write_bytes(b"image")
            annotation = [{"page_info": {"image_path": "sample.png", "page_attribute": {"layout": "single_column"}}, "layout_dets": [{"category_type": "text_block", "text": "abcdefgh"}]}]
            (root / "OmniDocBench.json").write_text(json.dumps(annotation), encoding="utf-8")
            result = export_omnidocbench_official_inputs(root, root / "export", converter=lambda _: "# parsed")
            self.assertEqual(result["page_count"], 1)
            self.assertTrue((root / "export" / "predictions" / "sample.md").is_file())
            self.assertEqual(len(json.loads((root / "export" / "OmniDocBench_subset.json").read_text(encoding="utf-8"))), 1)

    def test_omnidocbench_official_export_uses_manifest_selected_pages(self) -> None:
        """生产清单必须决定导出页面，并校验来源哈希和标注属性。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "dataset"; root.mkdir()
            selection_root = root / "selection"; (selection_root / "images").mkdir(parents=True)
            content = b"image"; (selection_root / "images" / "sample.png").write_bytes(content)
            annotation = [{"page_info": {"image_path": "sample.png", "page_attribute": {"layout": "single_column"}}, "layout_dets": [{"category_type": "text_block", "text": "abcdefgh"}]}]
            (root / "OmniDocBench.json").write_text(json.dumps(annotation), encoding="utf-8")
            selection = selection_root / "production_manifest.json"
            selection.write_text(json.dumps({"dataset": "opendatalab/OmniDocBench", "revision": "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec", "samples": [{"sample_id": "production_001", "relative_path": "images/sample.png", "sha256": sha256_bytes(content), "category": "scan_or_text", "page_attribute": {"layout": "single_column"}, "required_categories": ["text_block"]}]}), encoding="utf-8")
            result = export_omnidocbench_official_inputs(root, root / "export", converter=lambda _: "# parsed", selection_manifest=selection)
            manifest = json.loads((root / "export" / "official_export_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result["page_count"], 1)
            self.assertEqual(manifest["selection_manifest_filename"], "production_manifest.json")
            self.assertTrue((root / "export" / "predictions" / "sample.md").is_file())

    def test_vision_400_uses_json_prompt_fallback_and_audits_without_response(self) -> None:
        """结构化输出不兼容时只降级一次，并写入脱敏审计。"""
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VISION_API_KEY": "key", "VISION_BASE_URL": "https://api.wcode.net/v1"}):
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content='{"content_kind":"chart","confidence":0.8,"informative":true}'))]
            response.usage = MagicMock(prompt_tokens=3, completion_tokens=4)
            response._request_id = "request-1"
            client = MagicMock(); client.chat.completions.create.side_effect = [type("Error", (Exception,), {"status_code": 400})(), response]
            analyzer = VisionAnalyzer(Path(directory), allow_remote_data=True, max_images=1)
            with patch("Agent.knowledge_base.multimodal.vision.OpenAI", return_value=client):
                analysis = analyzer.analyze(b"image", "image/png")
            self.assertEqual(analysis.content_kind, "chart")
            self.assertEqual(client.chat.completions.create.call_count, 2)
            audit = (Path(directory) / "vision_audit.jsonl").read_text(encoding="utf-8")
            self.assertIn("success_json_prompt_fallback", audit)
            self.assertNotIn("content_kind", audit)

    def test_vision_cache_prevents_second_sdk_call(self) -> None:
        """相同图片、模型和 Prompt 命中缓存后不得再次调用远程 SDK。"""
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VISION_API_KEY": "key", "VISION_BASE_URL": "https://api.wcode.net/v1"}):
            response = MagicMock(); response.choices = [MagicMock(message=MagicMock(content='{"content_kind":"chart","confidence":0.8,"informative":true}'))]; response.usage = None; response._request_id = "request"
            client = MagicMock(); client.chat.completions.create.return_value = response
            analyzer = VisionAnalyzer(Path(directory), allow_remote_data=True, max_images=1)
            with patch("Agent.knowledge_base.multimodal.vision.OpenAI", return_value=client):
                first = analyzer.analyze(b"image", "image/png")
                second = analyzer.analyze(b"image", "image/png")
            self.assertEqual(first, second)
            self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_recorded_vision_failure_blocks_uncontrolled_retry(self) -> None:
        """失败状态必须在后续普通构建中阻止再次外发。"""
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VISION_API_KEY": "key", "VISION_BASE_URL": "https://api.wcode.net/v1", "VISION_MAX_RETRIES": "0"}):
            client = MagicMock(); client.chat.completions.create.side_effect = RuntimeError("timeout")
            analyzer = VisionAnalyzer(Path(directory), allow_remote_data=True, max_images=1)
            with patch("Agent.knowledge_base.multimodal.vision.OpenAI", return_value=client):
                with self.assertRaises(RuntimeError): analyzer.analyze(b"image", "image/png")
            retry_client = MagicMock(); retry = VisionAnalyzer(Path(directory), allow_remote_data=True, max_images=1)
            with patch("Agent.knowledge_base.multimodal.vision.OpenAI", return_value=retry_client):
                with self.assertRaisesRegex(RuntimeError, "already recorded"): retry.analyze(b"image", "image/png")
            retry_client.assert_not_called()
            failure = next(Path(directory).glob("*.failure.json")).read_text(encoding="utf-8")
            self.assertIn("RuntimeError", failure); self.assertNotIn("timeout", failure)

    def test_unenriched_title_only_image_is_not_indexed(self) -> None:
        """未增强且无本地正文的独立图片不得作为低价值标题向量写入。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "image.png"; source.write_bytes(b"not-a-real-image")
            service = MultimodalKnowledgeBaseMaintenance(asset_root=root / "assets", index_root=root / "indexes", active_config=root / "active.json")
            result = service.ingest([str(source)])
            manifest = json.loads((root / "indexes" / result["index_version"] / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result["unit_count"], 0)
            self.assertEqual(manifest["quality_observations"]["low_value_images_skipped"], 1)

    def test_maintenance_run_is_idempotent_and_stops_before_publish_on_gate_failure(self) -> None:
        """维护编排复用既有版本，门禁失败或取消都不得切换 active pointer。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source.md"; source.write_text("正文", encoding="utf-8")
            service = MultimodalKnowledgeBaseMaintenance(asset_root=root / "assets", index_root=root / "indexes", active_config=root / "active.json")
            version = service._index_version(service._manifest(service._scan([str(source)])[0]))
            (root / "indexes" / version).mkdir(parents=True)
            with patch.object(service, "ingest") as ingest, patch.object(service, "evaluate", return_value={"passed": False, "failures": ["quality_gate_failed"]}), patch.object(service, "publish") as publish:
                result = service.run([str(source)])
            self.assertEqual(result["status"], "gate_failed"); ingest.assert_not_called(); publish.assert_not_called()
            with patch.object(service, "publish") as publish:
                result = service.run([str(source)], cancel_check=lambda: True)
            self.assertEqual(result["status"], "cancelled"); publish.assert_not_called()

    def test_vision_rejects_model_or_provider_drift(self) -> None:
        """远程视觉边界必须固定为获准的 WCode 模型和域名。"""
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VISION_API_KEY": "key", "VISION_BASE_URL": "https://api.wcode.net/v1", "VISION_MODEL": "other/model"}):
            self.assertFalse(VisionAnalyzer(Path(directory), allow_remote_data=True).configured())
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VISION_API_KEY": "key", "VISION_BASE_URL": "https://api.example.test/v1", "VISION_MODEL": "qwen/qwen3-vl-flash"}):
            self.assertFalse(VisionAnalyzer(Path(directory), allow_remote_data=True).configured())

    def test_vision_concurrency_cap_serializes_extra_requests(self) -> None:
        """并发上限必须约束实际 SDK 调用，而不是只保留配置字段。"""
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"VISION_API_KEY": "key", "VISION_BASE_URL": "https://api.wcode.net/v1", "VISION_MAX_CONCURRENCY": "1"}):
            response = MagicMock(); response.choices = [MagicMock(message=MagicMock(content='{"content_kind":"chart","confidence":0.8,"informative":true}'))]; response.usage = None; response._request_id = "request"
            active = 0; peak = 0; lock = threading.Lock()
            def invoke(**kwargs):
                nonlocal active, peak
                with lock:
                    active += 1; peak = max(peak, active)
                time.sleep(0.03)
                with lock: active -= 1
                return response
            client = MagicMock(); client.chat.completions.create.side_effect = invoke
            analyzer = VisionAnalyzer(Path(directory), allow_remote_data=True, max_images=2)
            with patch("Agent.knowledge_base.multimodal.vision.OpenAI", return_value=client):
                workers = [threading.Thread(target=analyzer.analyze, args=(f"image-{index}".encode(), "image/png")) for index in range(2)]
                for worker in workers: worker.start()
                for worker in workers: worker.join()
            self.assertEqual(peak, 1)

    def test_parent_context_uses_same_page_text_only(self) -> None:
        """图片证据只能回取同文档、同页的正文上下文。"""
        image = {"document_id": "doc", "page_number": 2, "modality": "image", "raw_text": ""}
        units = [
            {"document_id": "doc", "page_number": 2, "modality": "text", "raw_text": "同页正文"},
            {"document_id": "doc", "page_number": 3, "modality": "text", "raw_text": "其他页正文"},
            {"document_id": "another", "page_number": 2, "modality": "text", "raw_text": "其他文档正文"},
        ]
        self.assertEqual(_parent_context(image, units), "同页正文")

    def test_retrieval_marks_missing_asset_without_discarding_evidence(self) -> None:
        """已发布索引资源失效时必须显式降级，而不能隐藏整条证据。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); version = "mm_" + "a" * 20; index_dir = root / "indexes" / version; index_dir.mkdir(parents=True)
            embedding = __import__("Agent.knowledge_base.multimodal.index", fromlist=["embedding_fingerprint"]).embedding_fingerprint()
            manifest = {"index_version": version, "embedding": embedding}
            (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            unit = {"unit_id": "unit_" + "a" * 64, "document_id": "doc_" + "b" * 64, "page_number": 1, "modality": "image", "content_kind": "chart", "raw_text": "", "vision_model": "qwen/qwen3-vl-flash", "asset_uri": "missing/image.png"}
            (index_dir / "units.jsonl").write_text(json.dumps(unit) + "\n", encoding="utf-8")
            active = {"index_version": version, "collection_name": "collection", "manifest_sha256": __import__("hashlib").sha256((index_dir / "manifest.json").read_bytes()).hexdigest(), "embedding": embedding}
            active_path = root / "runtime" / "active.json"; active_path.parent.mkdir(); active_path.write_text(json.dumps(active), encoding="utf-8")
            document = type("Document", (), {"metadata": {"unit_id": unit["unit_id"], "source_name": "样本"}, "page_content": "证据"})()
            database = MagicMock(); database.similarity_search_with_relevance_scores.return_value = [(document, 0.9)]
            with patch.dict(os.environ, {"MULTIMODAL_INDEX_ROOT": str(root / "indexes"), "MULTIMODAL_ACTIVE_INDEX_CONFIG": str(active_path), "MULTIMODAL_ASSET_DIR": str(root / "assets")}), patch("Agent.knowledge_base.multimodal.retrieval._embeddings", return_value=MagicMock()), patch("Agent.knowledge_base.multimodal.retrieval.Chroma", return_value=database):
                result = multimodal_rag_search(["测试"])
            self.assertTrue(result["success"])
            self.assertFalse(result["evidence"][0]["asset_available"])

    def test_retrieval_filters_unenriched_title_only_image(self) -> None:
        """历史索引中的标题级独立图片不得占据主要证据位。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); version = "mm_" + "a" * 20; index_dir = root / "indexes" / version; index_dir.mkdir(parents=True)
            embedding = __import__("Agent.knowledge_base.multimodal.index", fromlist=["embedding_fingerprint"]).embedding_fingerprint()
            manifest = {"index_version": version, "embedding": embedding}; (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            title_only = {"unit_id": "unit_" + "a" * 64, "document_id": "doc_" + "b" * 64, "modality": "image", "content_kind": "image", "raw_text": "", "vision_model": "", "asset_uri": "asset.png"}
            enriched = {"unit_id": "unit_" + "c" * 64, "document_id": "doc_" + "d" * 64, "modality": "image", "content_kind": "chart", "raw_text": "", "vision_model": "qwen/qwen3-vl-flash", "asset_uri": "asset.png"}
            (index_dir / "units.jsonl").write_text(json.dumps(title_only) + "\n" + json.dumps(enriched) + "\n", encoding="utf-8")
            active_path = root / "runtime" / "active.json"; active_path.parent.mkdir(); active_path.write_text(json.dumps({"index_version": version, "collection_name": "collection", "manifest_sha256": __import__("hashlib").sha256((index_dir / "manifest.json").read_bytes()).hexdigest(), "embedding": embedding}), encoding="utf-8")
            title_document = type("Document", (), {"metadata": {"unit_id": title_only["unit_id"]}, "page_content": "标题"})(); enriched_document = type("Document", (), {"metadata": {"unit_id": enriched["unit_id"]}, "page_content": "增强"})()
            database = MagicMock(); database.similarity_search_with_relevance_scores.return_value = [(title_document, 0.9), (enriched_document, 0.8)]
            with patch.dict(os.environ, {"MULTIMODAL_INDEX_ROOT": str(root / "indexes"), "MULTIMODAL_ACTIVE_INDEX_CONFIG": str(active_path), "MULTIMODAL_ASSET_DIR": str(root / "assets")}), patch("Agent.knowledge_base.multimodal.retrieval._embeddings", return_value=MagicMock()), patch("Agent.knowledge_base.multimodal.retrieval.Chroma", return_value=database):
                result = multimodal_rag_search(["测试"], max_results=1)
            self.assertEqual([item["unit_id"] for item in result["evidence"]], [enriched["unit_id"]])

    def test_retrieval_rejects_embedding_fingerprint_drift_before_chroma(self) -> None:
        """active、manifest 或运行时 embedding 不一致时不得打开 Chroma。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); version = "mm_" + "a" * 20; index_dir = root / "indexes" / version; index_dir.mkdir(parents=True)
            current = __import__("Agent.knowledge_base.multimodal.index", fromlist=["embedding_fingerprint"]).embedding_fingerprint()
            manifest = {"index_version": version, "embedding": current}; (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (index_dir / "units.jsonl").write_text("", encoding="utf-8")
            active_path = root / "runtime" / "active.json"; active_path.parent.mkdir(); active_path.write_text(json.dumps({"index_version": version, "collection_name": "collection", "manifest_sha256": __import__("hashlib").sha256((index_dir / "manifest.json").read_bytes()).hexdigest(), "embedding": current | {"model": "drifted"}}), encoding="utf-8")
            with patch.dict(os.environ, {"MULTIMODAL_INDEX_ROOT": str(root / "indexes"), "MULTIMODAL_ACTIVE_INDEX_CONFIG": str(active_path)}), patch("Agent.knowledge_base.multimodal.retrieval.Chroma") as chroma:
                result = multimodal_rag_search(["测试"])
            self.assertFalse(result["success"]); self.assertEqual(result["error_code"], "embedding_fingerprint_mismatch"); chroma.assert_not_called()

    def test_index_version_changes_with_embedding_or_vision_configuration(self) -> None:
        """影响向量或增强产物的配置变化必须生成新不可变版本。"""
        with tempfile.TemporaryDirectory() as directory:
            service = MultimodalKnowledgeBaseMaintenance(asset_root=Path(directory) / "assets", index_root=Path(directory) / "indexes", active_config=Path(directory) / "active.json")
            entries = [{"path": "unused", "relative_path": "source.md", "content_hash": "a" * 64}]
            baseline = service._index_version(service._manifest(entries, allow_remote_data=False))
            with patch.dict(os.environ, {"VISION_MODEL": "changed"}):
                changed_vision = service._index_version(service._manifest(entries, allow_remote_data=False))
            with patch("Agent.knowledge_base.multimodal.pipeline.embedding_fingerprint", return_value={"provider": "openai_compatible", "model": "changed", "mode": "api", "normalized": False}):
                changed_embedding = service._index_version(service._manifest(entries, allow_remote_data=False))
            self.assertNotEqual(baseline, changed_vision); self.assertNotEqual(baseline, changed_embedding)

    def test_quality_gate_blocks_complete_but_insufficient_enrichment(self) -> None:
        """质量不足即使完整性通过也必须阻止发布。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); version = "mm_" + "a" * 20; index_dir = root / "indexes" / version; index_dir.mkdir(parents=True)
            embedding = __import__("Agent.knowledge_base.multimodal.index", fromlist=["embedding_fingerprint"]).embedding_fingerprint()
            service = MultimodalKnowledgeBaseMaintenance(asset_root=root / "assets", index_root=root / "indexes", active_config=root / "runtime" / "active.json")
            content = b"source"; source_hash = sha256_bytes(content); document_id = stable_id("doc", {"path": "source.md", "content_hash": source_hash})
            source_uri = AssetStore(root / "assets").put(document_id, "source.md", content, category="source")
            unit = KnowledgeUnit(unit_id="unit_" + "a" * 64, document_id=document_id, modality="text", content_kind="paragraph", raw_text="正文", retrieval_text="正文", content_hash=sha256_bytes("正文".encode()), parser_name="text", parser_version="1", embedding_provider=embedding["provider"], embedding_model=embedding["model"], status=UnitStatus.COMPLETED)
            manifest = {"index_version": version, "embedding": embedding, "build_configuration": {}, "sources": [{"relative_path": "source.md", "content_hash": source_hash}], "documents": [{"document_id": document_id, "relative_path": "source.md", "content_hash": source_hash, "source_asset_uri": source_uri, "parser_artifacts": []}], "quality_policy": {"min_eligible_images": 1, "min_enriched_images": 1, "min_enrichment_rate": 1.0, "max_vision_failed_images": 0, "max_ocr_probe_failed": 0}, "quality_observations": {"eligible_images": 1, "enriched_images": 0, "vision_failed_images": 0, "skipped_images": 1}}
            (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8"); (index_dir / "units.jsonl").write_text(unit.model_dump_json() + "\n", encoding="utf-8"); (index_dir / "issues.jsonl").write_text("", encoding="utf-8")
            with patch("Agent.knowledge_base.multimodal.pipeline.StagedIndex.count", return_value=1):
                result = service.evaluate(version)
            self.assertFalse(result["passed"]); self.assertTrue(result["quality"]["failures"]); self.assertEqual(result["failures"], ["quality_gate_failed"])
            with self.assertRaisesRegex(ValueError, "blocking evaluation"):
                service.publish(version)
            manifest["quality_observations"]["enriched_images"] = 1
            (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with patch("Agent.knowledge_base.multimodal.pipeline.StagedIndex.count", return_value=1):
                result = service.evaluate(version)
            self.assertTrue(result["passed"]); self.assertEqual(service.publish(version)["status"], "published")

    def test_legacy_manifest_cannot_pass_new_quality_or_publication_gates(self) -> None:
        """缺少 P0 构建和质量契约的历史版本不得被默认零值放行。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); version = "mm_" + "a" * 20; index_dir = root / "indexes" / version; index_dir.mkdir(parents=True)
            embedding = __import__("Agent.knowledge_base.multimodal.index", fromlist=["embedding_fingerprint"]).embedding_fingerprint()
            unit = KnowledgeUnit(unit_id="unit_" + "a" * 64, document_id="doc_" + "b" * 64, modality="text", content_kind="paragraph", raw_text="正文", retrieval_text="正文", content_hash=sha256_bytes("正文".encode()), parser_name="text", parser_version="1", embedding_provider=embedding["provider"], embedding_model=embedding["model"], status=UnitStatus.COMPLETED)
            (index_dir / "manifest.json").write_text(json.dumps({"index_version": version, "embedding": embedding, "sources": [], "documents": []}), encoding="utf-8")
            (index_dir / "units.jsonl").write_text(unit.model_dump_json() + "\n", encoding="utf-8"); (index_dir / "issues.jsonl").write_text("", encoding="utf-8")
            service = MultimodalKnowledgeBaseMaintenance(asset_root=root / "assets", index_root=root / "indexes", active_config=root / "active.json")
            with patch("Agent.knowledge_base.multimodal.pipeline.StagedIndex.count", return_value=1):
                result = service.evaluate(version)
            self.assertFalse(result["passed"]); self.assertIn("legacy_manifest_missing_build_configuration", result["failures"]); self.assertIn("legacy_manifest_missing_quality_policy", result["quality"]["failures"])
            (index_dir / "evaluation.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "legacy manifest"):
                service.publish(version)

    def test_multimodal_is_the_default_and_only_rag_corpus(self) -> None:
        """未声明 corpus 时必须默认多模态，旧 medical 输入必须显式失败。"""
        payload = {"questions": [{"question": "解释文档", "intent": "证据", "priority": "high", "why_needed": "需要页面"}]}
        questions = normalize_rag_question_output(payload, 3)
        self.assertEqual(questions[0]["corpus"], "multimodal")

        payload["questions"][0]["corpus"] = "medical"
        with self.assertRaises(ValueError):
            normalize_rag_question_output(payload, 3)

    def test_default_rag_registry_keeps_original_tool_name(self) -> None:
        """默认 RAG 继续使用原工具名，但底层只绑定多模态 Service。"""
        self.assertEqual([tool.name for tool in build_rag_tools(MagicMock())], ["rag_enrichment_search"])

    def test_rag_runtime_defaults_to_published_multimodal_index(self) -> None:
        """原 RagRuntime 必须从多模态 active pointer 解析默认 collection。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version = "mm_test"
            version_dir = root / "indexes" / version
            (version_dir / "chroma").mkdir(parents=True)
            manifest = {"index_version": version, "embedding": {"provider": "local", "model": "model", "mode": "local", "normalized": True}}
            manifest_path = version_dir / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            active_path = root / "runtime" / "active.json"
            active_path.parent.mkdir()
            active_path.write_text(json.dumps({
                "index_version": version,
                "index_path": f"{version}/chroma",
                "collection_name": "causal_multimodal_mm_test",
                "manifest_sha256": __import__("hashlib").sha256(manifest_path.read_bytes()).hexdigest(),
                "embedding": manifest["embedding"],
            }), encoding="utf-8")
            embedding_config = {"status": "ready", "mode": "local", "provider": "local", "model": "model", "path": "model"}
            with patch.dict(os.environ, {"MULTIMODAL_INDEX_ROOT": str(root / "indexes"), "MULTIMODAL_ACTIVE_INDEX_CONFIG": str(active_path)}), patch("Agent.knowledge_base.rag_runtime.resolve_embedding_runtime_config", return_value=embedding_config):
                config = RagRuntimeConfig.from_environment()
            self.assertEqual(Path(config.vector_db_dir), version_dir / "chroma")
            self.assertEqual(config.collection_name, "causal_multimodal_mm_test")
            self.assertEqual(config.release_id, version)

    def test_original_rag_metadata_normalizer_preserves_multimodal_identity(self) -> None:
        """原检索链必须识别多模态 document、page、asset 和内容类型字段。"""
        from Agent.knowledge_base.query_rag import _normalize_chunk_metadata

        metadata = _normalize_chunk_metadata({
            "document_id": "doc_1",
            "page_number": 3,
            "asset_uri": "doc_1/images/chart.png",
            "modality": "image",
            "content_kind": "chart",
            "content_hash": "abc",
        }, "图表检索文本")
        self.assertEqual(metadata["doc_id"], "doc_1")
        self.assertEqual(metadata["page"], 3)
        self.assertEqual(metadata["source_name"], "chart.png")
        self.assertEqual(metadata["doc_type"], "chart")
        self.assertEqual(metadata["corpus"], "multimodal")

if __name__ == "__main__":
    unittest.main()
