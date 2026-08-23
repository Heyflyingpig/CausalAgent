"""因果分析图的共享状态定义。

本文件只描述节点之间传递的数据结构，不负责状态创建、持久化或业务处理。
"""

from operator import add
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from typing_extensions import NotRequired

from langchain_core.messages import BaseMessage


class CausalAgentState(TypedDict):
    """
    表示因果分析图在各节点之间传递的共享状态。

    这个 TypedDict 既是图的运行时状态，也是节点之间传递的上下文记忆。

    Attributes:
        messages: 对话消息历史。
        user_id: 当前用户 ID。
        username: 当前用户名。
        session_id: 当前聊天会话 ID。
        tool_call_request: 下游节点是否继续工具调用流程。
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
