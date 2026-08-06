"""构建 worker 进程级与 slot 级运行时依赖。"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
import logging
from pathlib import Path
import sys
from typing import Any

from langchain_openai import ChatOpenAI

from Agent.causal_agent.postgres_checkpointer import build_checkpointer
from config.settings import settings


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MCP_SERVER_PATH = PROJECT_ROOT / "Agent" / "CausalAgentMCP" / "mcp_server.py"
KNOWLEDGE_BASE_DIRECTORY = PROJECT_ROOT / "Agent" / "knowledge_base"


@dataclass(frozen=True)
class ProcessRuntime:
    """保存 worker 进程内共享、且不依赖 slot 生命周期的对象。"""

    llm: ChatOpenAI
    rag_available: bool


@dataclass(frozen=True)
class McpClientResources:
    """保存由 slot 的 ``AsyncExitStack`` 管理的 MCP 资源。"""

    client: Any
    session: Any
    tools: list[Any]


@dataclass(frozen=True)
class SlotRuntime:
    """显式保存一个 slot 的 LLM、MCP 生命周期资源、tools 与 graph。"""

    llm: ChatOpenAI
    mcp_resources: McpClientResources
    mcp_tools: list[Any]
    graph: Any


def create_llm() -> ChatOpenAI:
    """根据当前配置创建 LLM；配置缺失时立即失败。"""
    if not all([settings.MODEL, settings.BASE_URL, settings.API_KEY]):
        raise RuntimeError("LLM 配置不完整，无法初始化")

    logging.info("正在初始化 LLM 模型: %s", settings.MODEL)
    llm = ChatOpenAI(
        model=settings.MODEL,
        base_url=settings.BASE_URL,
        api_key=settings.API_KEY,
        streaming=False,
    )
    logging.info("LLM 实例初始化成功。")
    return llm


def check_rag_availability() -> bool:
    """只检查知识库目录，实际向量库仍在首次查询时延迟加载。"""
    logging.info("正在检查 RAG 知识库目录...")
    persist_directory = KNOWLEDGE_BASE_DIRECTORY / "db"
    if not persist_directory.exists():
        logging.warning(
            "知识库持久化目录不存在。请先运行 "
            "Agent/knowledge_base/build_knowledge.py 构建知识库。"
        )
        return False

    logging.info("RAG 启动检查通过；向量库将在首次实际查询时延迟初始化。")
    return True


def create_process_runtime() -> ProcessRuntime:
    """创建一次进程级运行时，消除对 ``app.agent.core`` 全局变量的依赖。"""
    return ProcessRuntime(
        llm=create_llm(),
        rag_available=check_rag_availability(),
    )


async def open_mcp_client_resources(
    process_stack: AsyncExitStack,
) -> McpClientResources:
    """为一个 slot 打开持久 MCP session 并加载 LangChain tools。"""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools
    except ImportError as exc:
        raise RuntimeError(
            "缺少 langchain-mcp-adapters，无法初始化 LangChain MCP adapter。"
        ) from exc

    client = MultiServerMCPClient(
        {
            "causal": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(MCP_SERVER_PATH)],
            }
        }
    )
    logging.info("MCP 初始化。")
    session = await process_stack.enter_async_context(client.session("causal"))
    tools = await load_mcp_tools(session)
    return McpClientResources(client=client, session=session, tools=tools)


async def create_slot_runtime(
    process_runtime: ProcessRuntime,
    process_stack: AsyncExitStack,
    checkpoint_pool: Any,
) -> SlotRuntime:
    """创建一个 slot 独占的 MCP 资源和 graph，并显式返回其依赖。"""
    from Agent.causal_agent.graph import create_graph_from_tools

    mcp_resources = await open_mcp_client_resources(process_stack)
    checkpointer = build_checkpointer(checkpoint_pool)
    graph = create_graph_from_tools(
        process_runtime.llm,
        mcp_resources.tools,
        checkpointer,
    )
    return SlotRuntime(
        llm=process_runtime.llm,
        mcp_resources=mcp_resources,
        mcp_tools=mcp_resources.tools,
        graph=graph,
    )
