import json
import logging
from typing import Dict, List, Literal

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.func import task
from pydantic import BaseModel, Field

from Agent.causal_agent.back_prompt import causal_rag_prompt
from Agent.causal_agent.state import CausalChatState


class RagQuestionItem(BaseModel):
    """用于描述单个知识库查询问题。"""

    question: str = Field(..., description="面向知识库的具体查询问题。")
    intent: str = Field(..., description="这个问题服务的分析意图。")
    priority: Literal["high", "medium", "low"] = Field(
        ...,
        description="这个问题对当前报告可信度的重要程度。",
    )
    why_needed: str = Field(..., description="为什么需要查询这个问题。")


class RagQuestionBundle(BaseModel):
    """用于承载结构化RAG问题列表。"""

    questions: List[RagQuestionItem] = Field(
        default_factory=list,
        description="根据对话历史和数据摘要生成的结构化知识库查询问题列表。",
    )


def _format_messages(messages: List[BaseMessage], max_messages: int = 6) -> str:
    formatted_messages = []
    for message in messages[-max_messages:]:
        role = getattr(message, "type", message.__class__.__name__)
        content = getattr(message, "content", "")
        formatted_messages.append(f"[{role}] {content}")
    return "\n".join(formatted_messages) if formatted_messages else "无可用对话历史。"


@task
async def get_rag_questions(
    state: CausalChatState,
    llm: ChatOpenAI,
    num_questions: int,
) -> List[Dict]:
    """
    生成结构化 RAG 查询问题。

    结构化输出失败时返回兜底问题，避免问题生成失败直接终止整条 Agent 链路。
    """
    logging.info("正在启动 RAG 问题生成任务...")
    try:
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

# 生成目标
1. 优先生成会增强报告可信度的问题，而不是泛泛介绍概念。
2. 问题要能直接帮助解释方法假设、风险来源、算法局限或因果推断陷阱。
3. 问题数量控制为 {num_questions} 个。
4. 每个问题都必须说明意图、优先级和为什么需要查询。

**你必须严格按照 `RagQuestionBundle` 的 schema 返回 JSON。**
**不要输出任何Markdown或额外解释。**
""",
                ),
                (
                    "human",
                    "请根据当前任务生成知识库查询问题。只返回 JSON 对象。",
                ),
            ]
        )

        question_generator_runnable = rag_prompt | llm | JsonOutputParser()
        logging.info("正在调用LLM生成结构化RAG查询问题...")

        llm_output = await question_generator_runnable.ainvoke(
            {
                "messages": _format_messages(state["messages"]),
                "data_summary": json.dumps(state.get("analysis_parameters", {}), indent=2, ensure_ascii=False),
                "preprocess_summary": state.get("preprocess_summary", ""),
                "system_role": causal_rag_prompt(),
                "num_questions": num_questions,
            }
        )

        response = RagQuestionBundle.model_validate(llm_output)
        questions = [question.model_dump() for question in response.questions]
        logging.info(f"LLM生成的RAG问题列表: {questions}")
        return questions
    except Exception as exc:
        logging.error(f"执行 RAG 问题生成时发生错误: {exc}", exc_info=True)
        return [
            {
                "question": "当前分析流程可能涉及哪些关键的因果识别假设？",
                "intent": "补充报告中的方法论假设说明",
                "priority": "high",
                "why_needed": "在问题生成失败时，至少保留一个能增强报告可信度的兜底问题。",
            }
        ]
