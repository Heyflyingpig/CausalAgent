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

    def test_runtime_prioritizes_an_explicit_table_request_without_false_positives(self):
        """显式图表请求走同模态 dense，普通“表达式”问题不得误触发。"""
        from Agent.knowledge_base import query_rag

        general = {
            "page_content": "正文",
            "metadata": {
                "unit_id": "text", "chunk_id": "text", "doc_id": "doc",
                "source_name": "source.pdf", "modality": "text",
            },
            "rerank_score": 1.0,
        }
        table = {
            "page_content": "表格",
            "metadata": {
                "unit_id": "table", "chunk_id": "table", "doc_id": "doc",
                "source_name": "source.pdf", "modality": "table",
            },
            "rerank_score": 0.5,
        }

        def fake_dense(_question, *args, **kwargs):
            return [table] if kwargs.get("metadata_filter") == {"modality": "table"} else [general]

        config = query_rag.RagRetrievalConfig()
        with patch.object(query_rag, "_dense_retrieve", side_effect=fake_dense), patch.object(
            query_rag, "_select_mmr_candidates", return_value=[general]
        ), patch.object(query_rag, "_sparse_retrieve", return_value=[]), patch.object(
            query_rag, "_merge_candidates", return_value=[general]
        ):
            explicit = query_rag._build_retrieval_trace_with_resources(
                "表 6.1 中的恢复率是什么？",
                config,
                vector_db=object(),
                embedding_function=object(),
                sparse_retriever=object(),
            )
            ordinary = query_rag._build_retrieval_trace_with_resources(
                "这个表达式是什么意思？",
                config,
                vector_db=object(),
                embedding_function=object(),
                sparse_retriever=object(),
            )

        self.assertEqual(config.final_top_k, 5)
        self.assertEqual(explicit["stages"]["final"][0]["metadata"]["unit_id"], "table")
        self.assertEqual(ordinary["stages"]["final"][0]["metadata"]["unit_id"], "text")


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


class RagNodeTests(unittest.TestCase):
    def test_mcp_adapter_text_block_list_is_parsed_as_success(self):
        """真实 MCP adapter 的文本块列表必须保留业务 success 字段。"""
        from langchain_core.messages import ToolMessage
        from Agent.tool_node.tool_message_adapter import parse_tool_message_json

        message = ToolMessage(
            content=[{"type": "text", "text": '{"success": true, "data": {"nodes": []}}'}],
            tool_call_id="call-1",
        )
        self.assertEqual(parse_tool_message_json(message), {"success": True, "data": {"nodes": []}})

    def test_mcp_adapter_text_block_dict_is_parsed_as_success(self):
        """真实 adapter 的单个 text block 也必须解出业务 success 字段。"""
        from langchain_core.messages import ToolMessage
        from Agent.tool_node.tool_message_adapter import parse_tool_message_json

        message = ToolMessage(
            content={"type": "text", "text": '{"success": true, "data": {"nodes": []}}'},
            tool_call_id="call-1",
        )
        self.assertEqual(parse_tool_message_json(message), {"success": True, "data": {"nodes": []}})

    def test_mcp_adapter_artifact_wrapper_is_parsed_as_success(self):
        """artifact structured_content 包装不得吞掉真实 MCP success 字段。"""
        from langchain_core.messages import ToolMessage
        from Agent.tool_node.tool_message_adapter import parse_tool_message_json

        message = ToolMessage(
            content="ignored",
            artifact={"structured_content": {"result": [{"type": "text", "text": '{"success": true}'}]}},
            tool_call_id="call-1",
        )
        self.assertEqual(parse_tool_message_json(message), {"success": True})

    def test_mcp_adapter_artifact_result_string_is_parsed_as_success(self):
        """真实 adapter 的 result 字符串必须递归还原为业务 JSON。"""
        from langchain_core.messages import ToolMessage
        from Agent.tool_node.tool_message_adapter import parse_tool_message_json

        message = ToolMessage(
            content="ignored",
            artifact={"structured_content": {"result": '{"success": true, "data": {}}'}},
            tool_call_id="call-1",
        )
        self.assertEqual(parse_tool_message_json(message), {"success": True, "data": {}})

    def test_mcp_failure_routes_to_terminal_normal_chat(self):
        """明确 MCP 失败不得回到 agent 形成无限循环。"""
        from Agent.causal_agent.edges import mcp_router

        self.assertEqual(mcp_router({"causal_analysis_result": {"success": False}}), "normal_chat")

    def test_successful_mcp_result_routes_to_rag(self):
        """成功 MCP 返回必须进入普通 rag 节点，而非回到 agent。"""
        from Agent.causal_agent.edges import mcp_router

        self.assertEqual(mcp_router({"causal_analysis_result": {"success": True}}), "rag")

    def test_mcp_subgraph_success_is_exported_to_parent_router(self):
        """子图完成后的 success 字段必须原样到达父图的 MCP 路由。"""
        from Agent.causal_agent.edges import mcp_router
        from Agent.causal_agent.graph import _mcp_parent_update

        parent_update = _mcp_parent_update(
            {"causal_analysis_result": {"success": True, "data": {}}, "tool_call_request": True}
        )
        self.assertEqual(parent_update["causal_analysis_result"]["success"], True)
        self.assertEqual(mcp_router(parent_update), "rag")

    def test_direct_rag_node_generates_questions_and_calls_service(self):
        """单一 RAG 节点必须直接生成问题、调用 Service 并写回结果。"""
        from Agent.causal_agent import nodes

        questions = [{"question": "解释图表", "corpus": "multimodal"}]
        expected = {"success": True, "questions": [], "evidence_count": 0, "summary": "ok"}
        service = MagicMock()
        service.get_response.return_value = expected
        with patch.object(nodes, "get_rag_questions", AsyncMock(return_value=questions)):
            result = asyncio.run(nodes.rag_node({"messages": []}, object(), service))
        service.get_response.assert_called_once_with(questions)
        self.assertEqual(result, {"knowledge_base_result": expected})

    def test_parent_graph_has_no_rag_subgraph(self):
        """父图只保留 MCP 子图，rag 必须是普通节点。"""
        from Agent.causal_agent.graph import build_graph

        graph = build_graph(MagicMock(), [], MagicMock(), checkpointer=False)
        self.assertEqual([name for name, _graph in graph.get_subgraphs()], ["mcp"])

    def test_successful_rag_flow_proceeds_to_postprocess(self):
        """RAG 成功后不得重新进入 agent 并再次调用 MCP。"""
        from Agent.causal_agent.graph import build_graph

        graph = build_graph(MagicMock(), [], MagicMock(), checkpointer=False)
        edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
        self.assertIn(("rag", "postprocess"), edges)
        self.assertNotIn(("rag", "agent"), edges)


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
