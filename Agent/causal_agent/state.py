from operator import add
from typing import Annotated, Any, Dict, List, Literal, NotRequired, Optional, TypedDict

from langchain_core.messages import BaseMessage


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
        file_content: 数据源文件内容字符串。
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
    fold_name: str

    route_decision: NotRequired[
        Literal["fold", "postprocess", "normal_chat", "inquiry_answer"]
    ]
    fold_decision: NotRequired[Literal["preprocess", "agent"]]

    tool_call_request: Optional[bool]

    analysis_parameters: Optional[dict]
    file_content: Optional[str]

    causal_analysis_result: Optional[dict]
    knowledge_base_result: Optional[Dict[str, Any]]

    preprocess_summary: Optional[str]
    postprocess_result: Optional[dict]

    final_report: Optional[str]
    visualization_mapping: Optional[dict]

    visualizations: Optional[dict]
