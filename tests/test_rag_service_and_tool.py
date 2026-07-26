import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from Agent.knowledge_base.rag_service import (
    UNAVAILABLE_RAG_RESULT,
    RagService,
    UnavailableRagService,
)


class RagServiceTests(unittest.TestCase):
    def test_unavailable_service_returns_stable_fresh_result(self):
        service = UnavailableRagService()
        first = service.get_response(["secret question"])
        second = service.get_response([])

        self.assertEqual(first, UNAVAILABLE_RAG_RESULT)
        self.assertEqual(second, UNAVAILABLE_RAG_RESULT)
        self.assertIsNot(first, second)
        self.assertNotIn("secret question", str(first))

    def test_each_question_loads_current_production_config(self):
        from Agent.knowledge_base import query_rag

        configs = [
            query_rag.RagRetrievalConfig(final_top_k=1),
            query_rag.RagRetrievalConfig(final_top_k=2),
        ]
        runtime = SimpleNamespace(
            config=SimpleNamespace(production_config_path="production.json"),
            vector_db=object(),
            embedding=object(),
            sparse_retriever=object(),
            answer_llm=object(),
        )
        service = RagService(runtime)
        seen_configs = []

        def fake_trace(_question, config=None):
            seen_configs.append(config)
            return {"stages": {"final": []}}

        with patch.object(service, "_load_retrieval_config", side_effect=configs), patch.object(
            service, "build_retrieval_trace", side_effect=fake_trace
        ), patch.object(
            service, "answer_question", side_effect=lambda payload, _evidence: {"question": payload["question"]}
        ), patch.object(
            query_rag, "format_rag_summary_for_prompt", return_value="summary"
        ):
            result = service.get_response(["q1", "q2"])

        self.assertEqual(seen_configs, configs)
        self.assertEqual([item["question"] for item in result["questions"]], ["q1", "q2"])

    def test_compatibility_exports_remain_available(self):
        from Agent.knowledge_base import query_rag

        for name in (
            "RagRetrievalConfig",
            "build_retrieval_trace",
            "get_vector_db_metadata_summary",
            "get_rag_response",
            "_get_embedding_function",
            "_answer_question",
            "_normalize_question_payload",
            "COLLECTION_NAME",
            "PRODUCTION_RAG_CONFIG_PATH",
            "get_production_rag_config_status",
        ):
            self.assertTrue(hasattr(query_rag, name), name)


class RagToolTests(unittest.TestCase):
    def test_original_tool_name_invokes_multimodal_service(self):
        """原 rag_enrichment_search 工具必须调用注入的多模态 Service。"""
        from Agent.tool_node.rag_tool_registry import build_rag_tools

        service = MagicMock()
        service.get_response.return_value = {
            "success": True,
            "questions": [],
            "evidence_count": 0,
            "summary": "ok",
        }
        tool = build_rag_tools(service)[0]
        result = asyncio.run(tool.coroutine(questions=["q1", "q2"], max_results=1))
        self.assertEqual(tool.name, "rag_enrichment_search")
        service.get_response.assert_called_once_with(["q1"])
        self.assertTrue(result["success"])

    def test_tool_degrades_only_the_failed_call(self):
        """多模态 Service 单次异常不得泄漏内部错误或污染后续调用。"""
        from Agent.tool_node.rag_tool_registry import build_rag_tools

        service = MagicMock()
        service.get_response.side_effect = [
            RuntimeError("internal secret detail"),
            {"success": True, "questions": [], "evidence_count": 0, "summary": "ok"},
        ]
        tool = build_rag_tools(service)[0]
        first = asyncio.run(tool.coroutine(questions=["q"], max_results=5))
        second = asyncio.run(tool.coroutine(questions=["q"], max_results=5))
        self.assertEqual(first, UNAVAILABLE_RAG_RESULT)
        self.assertTrue(second["success"])
        self.assertNotIn("internal secret detail", str(first))


class WorkerRagAssemblyTests(unittest.TestCase):
    def test_worker_shares_multimodal_rag_service_across_slots(self):
        """默认多模态 Runtime/Service 必须沿用原 worker 注入链路。"""
        from app.agent import worker

        rag_service = object()
        llm = object()
        run_slot = AsyncMock(return_value=None)
        with patch.object(worker, "check_database_readiness"), patch.object(
            worker.agent_core, "initialize_llm", return_value=True
        ), patch.object(
            worker.agent_core, "initialize_rag_service", return_value=rag_service
        ) as initialize_rag, patch.object(
            worker.agent_core, "llm", llm
        ), patch.object(
            worker.settings, "JOB_WORKERS", 3
        ), patch.object(
            worker, "_run_slot", run_slot
        ):
            asyncio.run(worker._main_async())

        initialize_rag.assert_called_once_with(llm)
        self.assertEqual(run_slot.await_count, 3)
        for call in run_slot.await_args_list:
            self.assertIs(call.args[1], rag_service)


if __name__ == "__main__":
    unittest.main()
