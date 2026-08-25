"""把 LangGraph v2 内部流转换为稳定的公开任务事件。"""

from __future__ import annotations

import hashlib
import time
from typing import Any


NODE_DESCRIPTIONS = {
    "agent": "分析用户意图",
    "fold": "加载文件并验证数据",
    "preprocess": "预处理数据",
    "mcp": "执行因果分析",
    "rag": "检索知识库",
    "web_search": "联网搜索",
    "postprocess": "校验并修正因果图",
    "report": "生成分析报告",
    "normal_chat": "生成回答",
    "inquiry_answer": "回答报告追问",
}
TEXT_STREAM_NODES = {"normal_chat", "inquiry_answer"}
TOOL_STAGE_NODES = {
    "mcp_planner": "mcp",
    "mcp_tool_node": "mcp",
    "mcp_result_parser": "mcp",
    "rag_question_planner": "rag",
    "rag_tool_node": "rag",
    "rag_result_parser": "rag",
    "rag_finalize": "rag",
}
DECISION_PROGRESS = {
    "fold": "已识别为因果分析请求",
    "normal_chat": "已识别为普通问答",
    "inquiry_answer": "已识别为报告追问",
    "postprocess": "已识别为已有结果的后续处理",
    "preprocess": "文件与数据验证完成",
    "agent": "需要补充分析输入",
}
DECISION_FIELDS = {
    "agent": "route_decision",
    "fold": "fold_decision",
}


def _opaque_id(*parts: Any) -> str:
    """根据内部标识生成不暴露 attempt/task 内容的稳定 ID。"""
    raw = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def sanitize_public_error(error: Any) -> str:
    """把内部异常归类为有限的用户可见错误，避免泄露连接和路径信息。"""
    name = error if isinstance(error, str) else type(error).__name__
    normalized = str(name).lower()
    if "timeout" in normalized:
        return "调用超时"
    if any(token in normalized for token in ("connection", "connect", "network")):
        return "服务连接失败"
    if any(token in normalized for token in ("rate", "limit")):
        return "服务当前繁忙"
    if any(token in normalized for token in ("permission", "auth")):
        return "服务授权失败"
    return "节点执行失败"


class LangGraphEventAdapter:
    """把 LangGraph v2 多流事件转换为稳定、可持久化的公开事件协议。"""

    def __init__(self, job_id: str | None, job_attempt: int):
        """初始化单次 job attempt 的阶段、重试和文字流状态。"""
        self.job_id = job_id or "untracked"
        self.job_attempt = job_attempt
        self.steps: dict[str, dict[str, Any]] = {}
        self.active_by_node: dict[str, str] = {}
        self.failed_attempts: dict[str, str] = {}
        self.streams: dict[str, dict[str, Any]] = {}

    def _base(self, event_type: str, step: dict[str, Any]) -> dict[str, Any]:
        """构造所有阶段事件共享的持久化字段。"""
        return {
            "type": event_type,
            "step_id": step["step_id"],
            "node_name": step["node_name"],
            "title": NODE_DESCRIPTIONS[step["node_name"]],
            "attempt": self.job_attempt,
        }

    def _active_step(self, node_name: str) -> dict[str, Any] | None:
        """获取指定父图节点当前尚未结束的阶段实例。"""
        task_id = self.active_by_node.get(node_name)
        return self.steps.get(task_id) if task_id else None

    def _parent_tool_step(self, node_name: str) -> dict[str, Any] | None:
        """把子图内部节点映射到当前 MCP/RAG 父阶段。"""
        parent_name = TOOL_STAGE_NODES.get(node_name)
        return self._active_step(parent_name) if parent_name else None

    def _task_event(self, namespace: Any, data: Any) -> list[dict[str, Any]]:
        """将根图 tasks 开始/结束转换为阶段生命周期事件。"""
        if namespace or not isinstance(data, dict):
            return []
        task_id = str(data.get("id") or "")
        node_name = data.get("name")
        if not task_id or node_name not in NODE_DESCRIPTIONS:
            return []
        if "input" in data:
            step = {
                "step_id": _opaque_id(self.job_id, self.job_attempt, task_id),
                "node_name": node_name,
                "started_at": time.monotonic(),
            }
            self.steps[task_id] = step
            self.active_by_node[node_name] = task_id
            return [self._base("node_start", step)]
        step = self.steps.get(task_id)
        if not step:
            return []
        event = self._base("node_end", step)
        event["duration"] = round(
            max(0.0, time.monotonic() - step["started_at"]),
            2,
        )
        event["status"] = "failed" if data.get("error") else "completed"
        if data.get("error"):
            event["message"] = sanitize_public_error(data.get("error"))
        if self.active_by_node.get(node_name) == task_id:
            self.active_by_node.pop(node_name, None)
        return [event]

    def _custom_event(self, data: Any) -> list[dict[str, Any]]:
        """只有失败后再次开始时，才把内部 attempt 转换为真正的重试。"""
        if not isinstance(data, dict):
            return []
        event_type = data.get("type")
        task_id = str(data.get("task_id") or "")
        node_name = data.get("node_name")
        if event_type == "node_attempt_failed" and task_id:
            self.failed_attempts[task_id] = sanitize_public_error(
                data.get("error_kind")
            )
            return []
        if event_type != "node_attempt_start" or not task_id:
            return []
        failure = self.failed_attempts.pop(task_id, None)
        if not failure:
            return []
        step = (
            self.steps.get(task_id)
            or self._active_step(node_name)
            or self._parent_tool_step(node_name)
        )
        if not step:
            return []
        discarded = self.streams.pop(step["step_id"], None)
        event = self._base("node_retry", step)
        event["message"] = failure
        if discarded:
            event["discard_stream_id"] = discarded["stream_id"]
        return [event]

    @staticmethod
    def _tool_call(message: Any) -> tuple[str | None, list[str]]:
        """只读取工具名和参数字段名，不返回参数值。"""
        calls = getattr(message, "tool_calls", None) or []
        if not calls:
            return None, []
        call = calls[0]
        if isinstance(call, dict):
            name = call.get("name")
            args = call.get("args")
        else:
            name = getattr(call, "name", None)
            args = getattr(call, "args", None)
        keys = sorted(str(key) for key in args)[:12] if isinstance(args, dict) else []
        return name, keys

    def _update_event(self, namespace: Any, data: Any) -> list[dict[str, Any]]:
        """从显式 State 和规范化结果生成 decision、progress 与工具摘要。"""
        if not isinstance(data, dict):
            return []
        events: list[dict[str, Any]] = []
        for node_name, output in data.items():
            if not isinstance(output, dict):
                continue
            step = self._active_step(node_name)
            if step:
                decision_field = DECISION_FIELDS.get(node_name)
                decision = output.get(decision_field) if decision_field else None
                if decision:
                    progress = self._base("progress", step)
                    progress["summary"] = DECISION_PROGRESS.get(
                        decision,
                        "路由判断完成",
                    )
                    events.append(progress)
                    event = self._base("decision", step)
                    event["summary"] = (
                        f"已决定进入：{NODE_DESCRIPTIONS.get(decision, decision)}"
                    )
                    events.append(event)
            tool_step = self._parent_tool_step(node_name)
            if not tool_step:
                continue
            messages = output.get("messages") or []
            latest = messages[-1] if messages else None
            tool_name, argument_keys = self._tool_call(latest)
            if tool_name:
                event = self._base("tool_call_start", tool_step)
                event.update(
                    {"tool_name": tool_name, "argument_keys": argument_keys}
                )
                events.append(event)
            if TOOL_STAGE_NODES[node_name] == "mcp":
                result = output.get("causal_analysis_result")
            elif node_name == "rag_finalize":
                result = output.get("rag_output")
            else:
                result = output.get("knowledge_base_result")
            if isinstance(result, dict):
                metadata = result.get("_tool_call") or {}
                event = self._base("tool_call_result", tool_step)
                event.update(
                    {
                        "tool_name": metadata.get("name") or tool_name or "工具",
                        "summary": (
                            "调用完成"
                            if result.get("success") is not False
                            else "调用失败"
                        ),
                    }
                )
                events.append(event)
        return events

    def _message_event(self, data: Any) -> list[dict[str, Any]]:
        """仅转换普通问答和报告追问的非空字符串 token。"""
        if not isinstance(data, (tuple, list)) or len(data) != 2:
            return []
        chunk, metadata = data
        if not isinstance(metadata, dict):
            return []
        node_name = metadata.get("langgraph_node")
        content = getattr(chunk, "content", None)
        if (
            node_name not in TEXT_STREAM_NODES
            or not isinstance(content, str)
            or not content
        ):
            return []
        step = self._active_step(node_name)
        if not step:
            return []
        stream = self.streams.get(step["step_id"])
        if not stream:
            stream = {
                "stream_id": _opaque_id(step["step_id"], time.monotonic_ns()),
                "sequence": 0,
            }
            self.streams[step["step_id"]] = stream
        stream["sequence"] += 1
        event = self._base("text_chunk", step)
        event.update(
            {
                "stream_id": stream["stream_id"],
                "sequence": stream["sequence"],
                "delta": content,
            }
        )
        return [event]

    def convert(self, chunk: Any) -> list[dict[str, Any]]:
        """转换一个 v2 StreamPart；无法识别的内部流会被忽略。"""
        if not isinstance(chunk, dict):
            return []
        stream_type = chunk.get("type")
        namespace = chunk.get("ns") or ()
        data = chunk.get("data")
        if stream_type == "tasks":
            return self._task_event(namespace, data)
        if stream_type == "custom":
            return self._custom_event(data)
        if stream_type == "updates":
            return self._update_event(namespace, data)
        if stream_type == "messages":
            return self._message_event(data)
        return []
