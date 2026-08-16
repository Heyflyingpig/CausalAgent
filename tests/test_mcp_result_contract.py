import json

from langchain_core.messages import ToolMessage

from Agent.tool_node.tool_message_adapter import parse_tool_message_json


def test_parse_mcp_result_unwraps_result_and_nested_json():
    """兼容旧 MCP 服务产生的 result 包装和二次 JSON 序列化。"""
    business_result = {"success": True, "data": {"nodes": [], "edges": []}}
    message = ToolMessage(
        content=json.dumps({"result": json.dumps(business_result)}),
        tool_call_id="call-1",
    )

    assert parse_tool_message_json(message) == business_result


def test_parse_mcp_result_unwraps_structured_content_artifact():
    """优先读取 langchain-mcp-adapters 提供的 structured_content。"""
    business_result = {"success": False, "message": "analysis failed"}
    message = ToolMessage(
        content="ignored",
        tool_call_id="call-1",
        artifact={
            "structured_content": {
                "result": json.dumps(business_result),
            }
        },
    )

    assert parse_tool_message_json(message) == business_result


def test_parse_mcp_result_keeps_plain_invalid_json_as_failure():
    """普通 ToolMessage 中的非 JSON 文本必须保留为可识别失败。"""
    message = ToolMessage(content="not-json", tool_call_id="call-1")

    result = parse_tool_message_json(message)

    assert result["success"] is False
    assert result["error_type"] == "ToolMessageProtocolError"
    assert "not valid JSON" in result["error"]
