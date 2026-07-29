import asyncio
import importlib
import sys

import pytest
from pydantic import BaseModel, ValidationError

from Agent.llm_structured_output import (
    StructuredOutputError,
    ainvoke_structured,
    invoke_structured,
)


class ExampleSchema(BaseModel):
    """测试用结构化返回模型。"""

    value: int


class FakeRunnable:
    """记录同步和异步调用次数的最小 Runnable。"""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.invoke_count = 0
        self.ainvoke_count = 0
        self.config = None

    def with_config(self, config):
        self.config = config
        return self

    def invoke(self, inputs):
        self.invoke_count += 1
        if self.error:
            raise self.error
        return self.result

    async def ainvoke(self, inputs):
        self.ainvoke_count += 1
        if self.error:
            raise self.error
        return self.result


class FakePrompt:
    """把管道构造定向到指定 FakeRunnable。"""

    def __init__(self, runnable):
        self.runnable = runnable

    def __or__(self, structured_llm):
        return self.runnable


class FakeLLM:
    """记录 with_structured_output 的协议参数。"""

    def __init__(self):
        self.calls = []
        self.copy_updates = []
        self.extra_body = {"existing": "value"}

    def model_copy(self, *, update):
        self.copy_updates.append(update)
        self.extra_body = update["extra_body"]
        return self

    def with_structured_output(self, schema, **kwargs):
        self.calls.append((schema, kwargs))
        return object()


def test_invoke_structured_returns_validated_schema_and_applies_config_once():
    """同步入口校验字典结果、应用配置并只调用模型一次。"""
    runnable = FakeRunnable(result={"value": 7})
    llm = FakeLLM()

    result = invoke_structured(
        llm=llm,
        schema=ExampleSchema,
        prompt=FakePrompt(runnable),
        inputs={"question": "test"},
        node_name="sync_node",
        config={"run_name": "sync-test"},
    )

    assert result == ExampleSchema(value=7)
    assert runnable.invoke_count == 1
    assert runnable.config == {"run_name": "sync-test"}
    assert llm.calls == [(ExampleSchema, {"method": "function_calling"})]
    assert llm.copy_updates == [
        {
            "extra_body": {
                "existing": "value",
                "thinking": {"type": "disabled"},
            }
        }
    ]


def test_ainvoke_structured_returns_schema_without_sync_blocking():
    """异步入口只使用 ainvoke，并返回 Schema 实例。"""
    runnable = FakeRunnable(result=ExampleSchema(value=9))
    llm = FakeLLM()

    result = asyncio.run(
        ainvoke_structured(
            llm=llm,
            schema=ExampleSchema,
            prompt=FakePrompt(runnable),
            inputs={},
            node_name="async_node",
        )
    )

    assert result.value == 9
    assert runnable.ainvoke_count == 1
    assert runnable.invoke_count == 0
    assert llm.calls == [(ExampleSchema, {"method": "function_calling"})]


@pytest.mark.parametrize(
    ("result", "model_error", "cause_type"),
    [
        ({"value": "not-an-int"}, None, ValidationError),
        (None, RuntimeError("model unavailable"), RuntimeError),
    ],
)
def test_structured_failures_have_metadata_cause_and_no_internal_retry(
    result,
    model_error,
    cause_type,
):
    """校验失败和模型异常都统一封装，且调用器内部不重试。"""
    runnable = FakeRunnable(result=result, error=model_error)

    with pytest.raises(StructuredOutputError) as captured:
        invoke_structured(
            llm=FakeLLM(),
            schema=ExampleSchema,
            prompt=FakePrompt(runnable),
            inputs={},
            node_name="failing_node",
        )

    error = captured.value
    assert error.node_name == "failing_node"
    assert error.schema_name == "ExampleSchema"
    assert error.original_exception_type == cause_type.__name__
    assert isinstance(error.__cause__, cause_type)
    assert runnable.invoke_count == 1


def test_rag_evidence_answer_failure_returns_insufficient_evidence(monkeypatch):
    """证据回答结构化失败时不伪造答案或引用。"""
    sys.modules.pop("Agent.knowledge_base.query_rag", None)
    query_rag = importlib.import_module("Agent.knowledge_base.query_rag")

    def fail_structured(**kwargs):
        raise StructuredOutputError(
            node_name="rag_evidence_answer",
            schema_name="RagAnswer",
            cause=ValueError("invalid"),
        )

    monkeypatch.setattr(query_rag, "invoke_structured", fail_structured)
    result = query_rag._answer_question(
        {
            "question": "PC 算法有什么限制？",
            "intent": "评估可信度",
            "priority": "high",
            "why_needed": "报告解释边界",
        },
        [
                {
                    "evidence_id": "E1",
                    "source": "knowledge.md",
                    "title": "PC 算法",
                    "page": 1,
                    "doc_type": "markdown",
                    "corpus": "causal",
                    "retrieval_source": "dense",
                "rerank_score": 0.8,
                "content": "证据内容",
            }
        ],
    )

    assert result["status"] == "insufficient_evidence"
    assert result["confidence"] == "low"
    assert result["citations"] == []
    assert "证据内容" not in result["answer"]
