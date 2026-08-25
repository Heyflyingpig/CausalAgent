"""构建 worker 进程级与 slot 级运行时依赖。"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
import logging
from pathlib import Path
import re
import sys
from typing import Any

from langchain_openai import ChatOpenAI

from Agent.causal_agent.postgres_checkpointer import build_checkpointer
from config.settings import settings


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MCP_SERVER_PATH = PROJECT_ROOT / "Agent" / "CausalAgentMCP" / "mcp_server.py"
RELEASE_ID_PATTERN = re.compile(r"^mm_[0-9a-f]{20}$")


@dataclass(frozen=True)
class RagReadiness:
    """保存 worker 启动时的轻量 RAG release 检查结果。"""

    status: str
    release_id: str | None = None
    error_code: str | None = None

    @property
    def available(self) -> bool:
        """只有明确的 available 状态才允许启用 RAG。"""
        return self.status == "available"


@dataclass(frozen=True)
class ProcessRuntime:
    """保存 worker 进程内共享、且不依赖 slot 生命周期的对象。"""

    llm: ChatOpenAI
    rag_available: bool
    rag_status: str | None = None
    rag_release_id: str | None = None
    rag_error_code: str | None = None

    def __post_init__(self) -> None:
        """为旧的显式构造调用补齐稳定的 RAG 状态名称。"""
        if self.rag_status is None:
            object.__setattr__(
                self,
                "rag_status",
                "available" if self.rag_available else "rag_unavailable",
            )


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


def _load_rag_runtime_config() -> Any:
    """读取 active release 的轻量 Runtime 配置，不初始化向量库。"""
    from Agent.knowledge_base.rag_runtime import RagRuntimeConfig

    return RagRuntimeConfig.from_environment()


def inspect_rag_readiness() -> RagReadiness:
    """检查 active pointer、manifest、embedding 指纹和索引目录。"""
    logging.info("[worker] checking RAG active release readiness")
    try:
        config = _load_rag_runtime_config()
        if config.embedding_config.get("status") != "ready":
            raise ValueError("active release embedding is unavailable")
        release_id = str(config.release_id)
        if RELEASE_ID_PATTERN.fullmatch(release_id) is None:
            raise ValueError("active release id is invalid")
        vector_db_dir = Path(config.vector_db_dir)
        if not vector_db_dir.is_dir():
            raise FileNotFoundError("active release vector directory is unavailable")
    except FileNotFoundError:
        readiness = RagReadiness(
            status="rag_unavailable",
            error_code="active_release_missing",
        )
    except ImportError:
        readiness = RagReadiness(
            status="rag_unavailable",
            error_code="rag_dependency_missing",
        )
    except (OSError, ValueError, TypeError, KeyError):
        readiness = RagReadiness(
            status="rag_unavailable",
            error_code="active_release_invalid",
        )
    except Exception:
        readiness = RagReadiness(
            status="rag_unavailable",
            error_code="active_release_check_failed",
        )
    else:
        readiness = RagReadiness(
            status="available",
            release_id=release_id,
        )

    if readiness.available:
        logging.info(
            "[worker] RAG readiness status=%s release=%s",
            readiness.status,
            readiness.release_id,
        )
    else:
        logging.warning(
            "[worker] RAG readiness status=%s code=%s",
            readiness.status,
            readiness.error_code,
        )
    return readiness


def check_rag_availability() -> bool:
    """兼容旧调用方，返回 active release 是否可用。"""
    return inspect_rag_readiness().available


def create_process_runtime() -> ProcessRuntime:
    """创建一次进程级运行时，消除对 ``app.agent.core`` 全局变量的依赖。"""
    readiness = inspect_rag_readiness()
    return ProcessRuntime(
        llm=create_llm(),
        rag_available=readiness.available,
        rag_status=readiness.status,
        rag_release_id=readiness.release_id,
        rag_error_code=readiness.error_code,
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
        rag_available=process_runtime.rag_available,
    )
    return SlotRuntime(
        llm=process_runtime.llm,
        mcp_resources=mcp_resources,
        mcp_tools=mcp_resources.tools,
        graph=graph,
    )
