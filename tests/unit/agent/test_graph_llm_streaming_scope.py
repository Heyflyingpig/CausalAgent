import ast
import unittest
from pathlib import Path


GRAPH_PATH = Path(__file__).resolve().parents[3] / "Agent" / "causal_agent" / "graph.py"


def _node_llm_bindings() -> dict[str, str]:
    """读取父图节点绑定的 LLM 变量名，约束流式能力的公开边界。"""
    module = ast.parse(GRAPH_PATH.read_text(encoding="utf-8"))
    bindings: dict[str, str] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "bind_node":
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        event_name = keywords.get("event_node_name")
        llm = keywords.get("llm")
        if isinstance(event_name, ast.Constant) and isinstance(llm, ast.Name):
            bindings[str(event_name.value)] = llm.id
    return bindings


class TestGraphLlmStreamingScope(unittest.TestCase):
    def test_only_public_answer_nodes_use_streaming_llm(self):
        bindings = _node_llm_bindings()

        self.assertEqual(bindings["preprocess"], "llm")
        self.assertEqual(bindings["postprocess"], "llm")
        self.assertEqual(bindings["report"], "llm")
        self.assertEqual(bindings["normal_chat"], "streaming_llm")
        self.assertEqual(bindings["inquiry_answer"], "streaming_llm")


if __name__ == "__main__":
    unittest.main()
