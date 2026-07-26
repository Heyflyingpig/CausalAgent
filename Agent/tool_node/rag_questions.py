import json
import logging
from typing import Dict, List, Literal

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.func import task
from pydantic import BaseModel, Field

from Agent.llm_structured_output import ainvoke_structured
from Agent.causal_agent.back_prompt import causal_rag_prompt
from Agent.causal_agent.state import CausalAgentState


class RagQuestionItem(BaseModel):
    """用于描述单个知识库查询问题。"""

    question: str = Field(
        ...,
        description="面向知识库的具体查询问题。",
    )
    intent: str = Field(..., description="这个问题服务的分析意图。")
    priority: Literal["high", "medium", "low"] = Field(
        ...,
        description="这个问题对当前报告可信度的重要程度。",
    )
    why_needed: str = Field(
        ...,
        description="为什么需要查询这个问题。",
    )
    corpus: Literal["multimodal"] = Field(
        default="multimodal",
        description="查询目标语料范围；当前默认且唯一支持多模态公共资料索引。",
    )



class RagQuestionBundle(BaseModel):
    """用于承载结构化RAG问题列表。"""

    questions: List[RagQuestionItem] = Field(
        default_factory=list,
        min_length=1,
        description="根据对话历史和数据摘要生成的结构化知识库查询问题列表。",
    )


def normalize_rag_question_output(bundle: RagQuestionBundle, max_questions: int) -> List[Dict]:
    """把已校验的 Schema 实例转换为 RAG 工具输入。"""
    questions = [question.model_dump() for question in bundle.questions[:max_questions]]
    if not questions:
        raise ValueError("RAG question output must contain at least one question.")
    return questions


def _format_messages(messages: List[BaseMessage], max_messages: int = 6) -> str:
    formatted_messages = []
    for message in messages[-max_messages:]:
        role = getattr(message, "type", message.__class__.__name__)
        content = getattr(message, "content", "")
        formatted_messages.append(f"[{role}] {content}")
    return "\n".join(formatted_messages) if formatted_messages else "无可用对话历史。"


def _format_causal_summary(state: CausalAgentState) -> str:
    """将因果分析结果转换为适合问题生成 prompt 的摘要文本。"""
    causal_result = state.get("causal_analysis_result") or {}
    if not causal_result:
        return "当前还没有可用的因果分析结果。"
    try:
        return json.dumps(causal_result, indent=2, ensure_ascii=False)
    except TypeError:
        return str(causal_result)


@task
async def get_rag_questions(
    state: CausalAgentState,
    llm: ChatOpenAI,
    max_questions: int,
) -> List[Dict]:
    """
    生成结构化 RAG 查询问题。

    结构化输出失败时直接抛出异常，由 LangGraph 节点级容错统一降级。
    """
    logging.info("正在启动 RAG 问题生成任务...")
    rag_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
                system role: {system_role}

                你是一个因果推断领域的知识管理专家。你的任务不是泛泛生成教材式问题，而是围绕当前分析任务，生成最能增强报告可信度的知识库查询问题。

                # 最近对话
                {messages}

                # 数据摘要
                {data_summary}

                # 预处理总结
                {preprocess_summary}

                # 因果分析摘要
                {causal_summary}

                # 生成目标
                1. 优先生成会增强报告可信度的问题，而不是泛泛介绍概念。
                2. 问题要能直接帮助解释方法假设、风险来源、算法局限或因果推断陷阱。
                3. 由你根据任务复杂度决定问题数量，但最多只能生成 {max_questions} 个。
                4. 如果一个问题已经足够，就只生成一个；不要为了凑数量而重复提问。
                5. 每个问题都必须说明意图、优先级、为什么需要查询和 corpus。
                6. corpus 固定为 multimodal；所有问题都查询已发布的多模态公共资料索引。

                # 输出格式
                必须只返回一个 JSON object，根对象必须包含 questions 字段，不允许直接返回数组。
                questions 必须是数组，每个元素必须包含 question、intent、priority、why_needed、corpus。
                priority 只能是 high、medium 或 low。

                示例：
                {{
                  "questions": [
                    {{
                      "question": "PC算法在隐藏混杂变量存在时有哪些主要风险？",
                      "intent": "评估因果发现结果的可信度",
                      "priority": "high",
                      "why_needed": "帮助报告说明算法假设和结果解释边界",
                      "corpus": "multimodal"
                    }}
                  ]
                }}

                不要输出 Markdown，不要输出额外解释。
                """,
            ),
            (
                "human",
                "请根据当前任务生成知识库查询问题。只返回 JSON 对象。",
            ),
        ]
    )

    logging.info("正在调用LLM生成结构化RAG查询问题...")
    bundle = await ainvoke_structured(
        llm=llm,
        schema=RagQuestionBundle,
        prompt=rag_prompt,
        inputs={
            "messages": _format_messages(state["messages"]),
            "data_summary": json.dumps(state.get("analysis_parameters", {}), indent=2, ensure_ascii=False),
            "preprocess_summary": state.get("preprocess_summary", ""),
            "causal_summary": _format_causal_summary(state),
            "system_role": causal_rag_prompt(),
            "max_questions": max_questions,
        },
        node_name="rag_question_planner",
    )

    questions = normalize_rag_question_output(bundle, max_questions=max_questions)
    logging.info(f"LLM生成的RAG问题列表: {questions}")
    return questions
