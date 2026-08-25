from operator import add
from typing import Annotated, Any, Dict, List, Literal, NotRequired, Optional, TypedDict

from langchain_core.messages import BaseMessage, ToolMessage


class FileSummary(TypedDict, total=False):
    """当前 Job 的冻结文件元数据和受限数据摘要。"""

    user_file_id: Optional[int]
    object_id: Optional[int]
    file_hash: Optional[str]
    filename: Optional[str]
    rows: Optional[int]
    columns: List[str]


class CausalAgentState(TypedDict):
    """
    Represents the state of our graph. This TypedDict acts as the "memory"
    or "state" that is passed between all the nodes in the graph.

    Attributes:
        messages: The history of messages in the conversation.
        user_id: The ID of the current user.
        username: The name of the current user.
        session_id: The ID of the current chat session.
        tool_call_request: Whether downstream nodes should continue the tool flow.
        analysis_parameters: 数据摘要及分析参数。
        file_summary: 文件的有限数据摘要。
        causal_analysis_result: 因果分析任务结果。
        knowledge_base_result: 结构化RAG结果，包含问题、证据链和汇总摘要。
        preprocess_summary: 预处理阶段的自然语言总结。
        postprocess_result: 后处理补充结果。
        final_report: 最终报告内容。
        visualization_mapping: 图表占位符映射。
        visualizations: 可视化原始结果。
    """

    messages: Annotated[List[BaseMessage], add]

    username: str
    user_id: int
    session_id: str
    job_id: NotRequired[str]
    file_summary: NotRequired[Optional[FileSummary]]

    route_decision: NotRequired[
        Literal["fold", "postprocess", "normal_chat", "inquiry_answer"]
    ]
    fold_decision: NotRequired[Literal["preprocess", "agent", "normal_chat"]]

    tool_call_request: Optional[bool]

    analysis_parameters: Optional[dict]

    causal_analysis_result: Optional[dict]
    knowledge_base_result: Optional[Dict[str, Any]]
    web_search_result: Optional[dict]

    preprocess_summary: Optional[str]
    postprocess_result: Optional[dict]

    final_report: Optional[str]
    visualization_mapping: Optional[dict]

    visualizations: Optional[dict]


class RagSubgraphState(TypedDict, total=False):
    """RAG 子图的私有状态。

    父图只通过适配节点提供四个只读上下文字段，并最终接收
    ``rag_output`` 的投影结果；问题列表、ToolMessage 和解析中间结果
    不会回写到 ``CausalAgentState``。
    """

    messages: Annotated[List[BaseMessage], add]

    analysis_parameters: Optional[dict]
    preprocess_summary: Optional[str]
    causal_analysis_result: Optional[dict]

    rag_route: Literal["call_tool", "parse", "finish"]
    rag_questions: List[Dict[str, Any]]
    rag_tool_message: Optional[ToolMessage]
    rag_parse_result: Optional[Dict[str, Any]]
    rag_status: Literal["available", "unavailable", "protocol_error"]
    rag_output: Optional[Dict[str, Any]]


class WebSearchInput(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    analysis_parameters: Optional[dict]
    causal_analysis_result: Optional[dict]
    knowledge_base_result: Optional[dict]


class WebSearchOutput(TypedDict):
    web_search_result: Optional[dict]


class WebSearchState(WebSearchInput, WebSearchOutput):
    planner: dict
    search: dict
