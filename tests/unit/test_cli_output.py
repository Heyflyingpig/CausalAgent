"""共享 CLI 输出适配器和 RAG 模块导入链回归测试。"""

from __future__ import annotations

import importlib

from observability.cli import write_cli_output


def test_write_cli_output_writes_text_to_stdout(capsys):
    write_cli_output("result")

    assert capsys.readouterr().out == "result\n"


def test_benchmark_v2_import_chain_is_available():
    module = importlib.import_module(
        "Agent.knowledge_base.rag.operation_datasets.benchmark_v2"
    )

    assert module.DEFAULT_GOLD_V2_OUTPUT.name == "pearl_gold_v2.json"
