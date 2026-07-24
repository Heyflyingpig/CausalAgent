import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
    def test_tool_schema_does_not_expose_service_and_applies_max_results(self):
        from Agent.tool_node.rag_tool_registry import build_rag_tools

        class RecordingService:
            def __init__(self):
                self.questions = None

            def get_response(self, questions):
                self.questions = questions
                return {"success": True, "questions": [], "evidence_count": 0, "summary": "ok"}

        service = RecordingService()
        rag_tool = build_rag_tools(service)[0]
        schema = rag_tool.args_schema.model_json_schema()["properties"]
        result = asyncio.run(
            rag_tool.ainvoke({"questions": ["q1", "q2", "q3"], "max_results": 2})
        )

        self.assertEqual(set(schema), {"questions", "max_results"})
        self.assertEqual(service.questions, ["q1", "q2"])
        self.assertTrue(result["success"])

    def test_tool_degrades_only_failed_call_and_retries_later_calls(self):
        from Agent.tool_node.rag_tool_registry import build_rag_tools

        class FlakyService:
            def __init__(self):
                self.calls = 0

            def get_response(self, _questions):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("internal secret detail")
                return {"success": True, "questions": [], "evidence_count": 0, "summary": "ok"}

        service = FlakyService()
        rag_tool = build_rag_tools(service)[0]
        first = asyncio.run(rag_tool.ainvoke({"questions": ["q"]}))
        second = asyncio.run(rag_tool.ainvoke({"questions": ["q"]}))

        self.assertEqual(first, UNAVAILABLE_RAG_RESULT)
        self.assertTrue(second["success"])
        self.assertNotIn("internal secret detail", str(first))


class WorkerRagAssemblyTests(unittest.TestCase):
    def test_all_slots_receive_same_service_when_rag_is_unavailable(self):
        from app.agent import worker

        unavailable = UnavailableRagService()
        run_slot = AsyncMock(return_value=None)
        with patch.object(worker, "check_database_readiness"), patch.object(
            worker.agent_core, "initialize_llm", return_value=True
        ), patch.object(
            worker.agent_core, "initialize_rag_service", return_value=unavailable
        ) as initialize_rag, patch.object(
            worker.agent_core, "llm", object()
        ), patch.object(
            worker.settings, "JOB_WORKERS", 3
        ), patch.object(
            worker, "_run_slot", run_slot
        ):
            asyncio.run(worker._main_async())

        initialize_rag.assert_called_once()
        self.assertEqual(run_slot.await_count, 3)
        for call in run_slot.await_args_list:
            self.assertIs(call.args[1], unavailable)


if __name__ == "__main__":
    unittest.main()
