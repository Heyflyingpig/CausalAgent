import asyncio
from .state import CausalChatState
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from typing import Literal, Optional, Any, List, Tuple, Dict
import logging
import json
import io
import pandas as pd
import numpy as np
import networkx as nx
from mcp import ClientSession
from langgraph.func import task
from langgraph.types import interrupt
from Agent.llm_structured_output import StructuredOutputError, ainvoke_structured

## 基本配置
from config.settings import settings

## 导入人设
## 因果分析人设
from .back_prompt import causal_prompt
## 数据分析人设
from .back_prompt import data_prompt
## 知识库查询人设
from .back_prompt import causal_rag_prompt
## 报告人设
from .back_prompt import causal_report_prompt

# 数据库
from Database.agent_connect import get_file_content, get_recent_file


def llm_prompt_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """过滤掉 ToolNode 内部转录，避免把工具调用协议消息回放给后续 LLM。"""
    safe_messages = []
    for message in messages:
        if isinstance(message, ToolMessage) or getattr(message, "type", None) == "tool":
            continue
        if getattr(message, "tool_calls", None) or getattr(message, "invalid_tool_calls", None):
            continue
        if getattr(message, "additional_kwargs", {}).get("tool_calls"):
            continue
        safe_messages.append(message)
    return safe_messages

class RouteQuery(BaseModel):
    """定义Agent决策的选项。"""
    route: Literal["postprocess", "fold", "normal_chat","inquiry_answer"] = Field(
        ...,
        description="根据用户的对话历史和意图，选择下一步应该走的路径。"
    )

# agentnode节点用于做初步的decision
def _latest_human_text(state: CausalChatState) -> str:
    """Return the latest human message content from the graph state."""
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            content = getattr(message, "content", "")
            return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return ""


def _is_explicit_causal_analysis_request(text: str) -> bool:
    """Detect requests that should deterministically enter the causal analysis flow."""
    normalized = text.lower()
    has_data_target = any(token in normalized for token in (".csv", "csv", "pc")) or any(
        token in text for token in ("文件", "数据", "读取", "上传")
    )
    has_causal_intent = any(
        token in text
        for token in ("因果分析", "因果推断", "因果边", "边合理性", "后处理", "因果发现")
    )
    has_action = any(
        token in text
        for token in ("分析", "执行", "运行", "读取", "处理", "生成报告", "立即", "使用")
    )
    return has_data_target and has_causal_intent and has_action


async def agent_node(state: CausalChatState, llm: ChatOpenAI) -> dict:

    """
    Agent节点，是图的起点，用于判断是否需要进入causal循环，
    根据当前状态强制LLM做出四选一的决策，然后将该决策转化为消息。
    """
    logging.info(" 步骤: Agent 节点 (LLM 决策) ")

    causal_analysis_result = state.get('causal_analysis_result') or {}
    if causal_analysis_result and causal_analysis_result.get("success") is False:
        error_message = (
            causal_analysis_result.get("message")
            or causal_analysis_result.get("error")
            or "因果分析工具执行失败。"
        )
        response_message = AIMessage(
            content=f"决策：普通问答。工具执行失败：{error_message}",
            name="agent"
        )
        return {"messages": [response_message], "route_decision": "normal_chat"}

    # 检查生成报告所需的有效分析结果是否已存在。
    has_tool_results = causal_analysis_result.get("success") is True

    latest_human_text = _latest_human_text(state)
    if not has_tool_results and _is_explicit_causal_analysis_request(latest_human_text):
        logging.info("检测到明确因果分析请求，绕过LLM路由并进入文件加载模块。")
        response_message = AIMessage(content="决策：信息不全，启动文件加载模块。", name="agent")
        return {"messages": [response_message], "route_decision": "fold"}
    agent_prompt = """
            你是一个专业的AI助手路由中枢。你的任务是根据用户的对话历史和当前状态，决定下一步的最佳路径。
            
            # 用户需求或者对话历史:{messages}
            # 当前状态摘要:
            - 是否已获得分析工具的结果: {has_tool_results}
            - 是否已获取到了最终的报告：{final_report}

            # 你的决策选项:
            1. `postprocess`: 如果已经获得了因果分析结果 ({has_tool_results} is True)，可以选择此路径以进入后处理模块。
            2. `fold`: 如果用户想要进行因果分析 (例如，对话中提到“分析”、“处理数据”或与“因果推断”相关的用语)，但我们还没有分析结果 ({has_tool_results} is False)，选择此路径以启动文件加载模块。
            3. `normal_chat`: 如果用户的提问只是一个与因果领域不相关的消息，不需要调用任何复杂的因果分析工具，选择此路径。
            4. `inquiry_answer`: 如果已经获取到了最终的报告（{final_report} is not None），选择此路径以直接根据报告回答用户的问题。
            
            请根据下面的对话历史，做出你的选择。
            你必须按照RouteQuery返回一个只包含 "route" 键的 JSON 对象格式来返回你的决策。
            **绝对不要**在你的回复中包含任何Markdown格式（例如 ```json ... ```）。
            例如:
            {{
                "route": "postprocess"
            }}
            """
    # 构建引导LLM决策的Prompt 
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", agent_prompt),
            ("human", "请根据上述指示生成路径。"),
        ]
    )
    
    logging.info("正在调用LLM进行路由决策...")
    try:
        structured_response = await ainvoke_structured(
            llm=llm,
            schema=RouteQuery,
            prompt=prompt,
            inputs={
                "messages": state["messages"][-1],
                "has_tool_results": has_tool_results,
                "final_report": state.get("final_report", None)
            },
            node_name="agent",
        )
        route_decision = structured_response.route

    except StructuredOutputError as e:
        logging.warning(f"无法从LLM响应中解析或验证路由决策: {e}。将回退到 normal_chat。")
        route_decision = "normal_chat"

    logging.info(f"LLM决策结果: {route_decision}")

    # 根据LLM的结构化决策，生成用于路由的消息 
    if route_decision == 'postprocess':
        response_message = AIMessage(content="决策：信息完备，进入后处理模块。", name="agent")
    elif route_decision == 'fold':
        response_message = AIMessage(content="决策：信息不全，启动文件加载模块。", name="agent")
    elif route_decision == 'inquiry_answer':
        response_message = AIMessage(content="决策：报告已获取，进入根据报告追问模块。", name="agent")
    else: # 'normal_chat'
        response_message = AIMessage(content="决策：普通问答。", name="agent")

    # 只返回新消息，不修改 state["messages"]
    return {"messages": [response_message], "route_decision": route_decision}

class foldQuery(BaseModel):
    """从用户对话中提取文件名及因果分析所需的关键参数。"""
    filename: Optional[str] = Field(
        None,
        description="从用户对话中识别出的要分析的数据文件名 (e.g., 'data.csv')。如果未明确提及，则留空。"
    )
    target: Optional[str] = Field(
        None,
        description="从用户对话中识别出的目标变量(target)或结果变量(outcome)。如果未提及，则留空。"
    )
    treatment: Optional[str] = Field(
        None,
        description="从用户对话中识别出的处理变量(treatment)或干预变量(intervention)。如果未提及，则留空。"
    )

## fold节点用到的函数
from Agent.Processing.fold_processing import get_data_summary
from Agent.Processing.fold_verify import validate_analysis
from Agent.Processing.data_visualize import generate_visualizations


async def fold_node(state: CausalChatState, llm: ChatOpenAI) -> dict:
    """
    文件加载、解析与验证节点。
    1.  使用LLM从对话中一次性提取文件名、目标和处理变量。
    2.  从数据库加载文件内容。
    3.  运行 get_data_summary 进行全面的数据分析。
    4.  调用 validate_analysis 进行严格的条件验证。
    5.  根据验证结果，决策进入 'preprocess' 节点或 'ask_human' 节点。
    """
    logging.info(" 步骤: 文件加载、解析与验证节点 ")
    user_id = state.get("user_id")

    # 1. 使用LLM一次性提取文件名和分析意图
    prompt = ChatPromptTemplate.from_messages([
            ("system",
            """你是一个智能助手，你的任务是从用户的最新消息中识别出以下信息，并以JSON格式返回：
            1.  用户想要分析的文件名 (通常以 `.csv` 结尾)。
            2.  用户关心的目标变量 (target/outcome)。
            3.  用户想要评估效果的处理变量 (treatment/intervention)。

            - 如果用户明确提到了文件名，请提取它。
            - 如果用户只是说"分析数据"或"用最新的文件"，没有指定具体名称，请将 `filename` 字段设为 null（不要使用字符串 "None"）。
            - 如果用户提到了目标或处理变量，请提取它们。如果没提，请设为 null（不要使用字符串 "None"）。

            示例:
            - 用户: "用 `marketing_campaign.csv` 帮我分析一下'销售额'和'促销活动'的关系..."
            -> 提取: `filename='marketing_campaign.csv'`, `target='销售额'`, `treatment='促销活动'`
            - 用户: "分析一下我的数据，看看是什么影响了客户流失"
            -> 提取: `filename=null`, `target='客户流失'`, `treatment=null`
            - 用户: "帮我跑一下最新的数据"
            -> 提取: `filename=null`, `target=null`, `treatment=null`
            
            你必须严格按照 `foldQuery` 的 schema 返回一个 JSON 对象。
            **绝对不要**在你的回复中包含任何Markdown格式或解释性文字。
            **重要：如果某个字段为空，请使用 JSON 的 null 值，而不是字符串 "None"。**

            示例输出（所有字段都有值）:
            {{
                "filename": "marketing_campaign.csv",
                "target": "销售额",
                "treatment": "促销活动"
            }}
            
            示例输出（部分字段为空）:
            {{
                "filename": null,
                "target": "客户流失",
                "treatment": null
            }}
            
            """),
            MessagesPlaceholder(variable_name="messages"),
        ])
    try:
        structured_response = await ainvoke_structured(
            llm=llm,
            schema=foldQuery,
            prompt=prompt,
            inputs={"messages": llm_prompt_messages(state["messages"])},
            node_name="fold",
        )

        filename = structured_response.filename
        target = structured_response.target
        treatment = structured_response.treatment
        
    except StructuredOutputError as e:
        logging.error(f"无法从LLM响应中解析或验证提取信息: {e}。将返回错误值")
        filename = None
        target = None
        treatment = None
    
    loaded_filename = None
    
    logging.info(f"filename: {filename}, state.get('fold_name'): {state.get('fold_name')}")
    try:
        if filename :
            file_content_bytes = await asyncio.to_thread(get_file_content, user_id, filename)
            state['fold_name'] = filename
            
            # 注意这里的文件名后续并没有用到
            loaded_filename = filename
        elif state.get('fold_name'):
            loaded_filename = state.get('fold_name')
            file_content_bytes = await asyncio.to_thread(get_file_content, user_id, loaded_filename)

        else:
            file_content_bytes , loaded_filename = await asyncio.to_thread(get_recent_file, user_id)

        if not file_content_bytes or not loaded_filename:
            raise FileNotFoundError("找不到任何可供分析的文件。请先上传一个CSV文件。")
        
        state['fold_name'] = loaded_filename
        file_content_str = file_content_bytes.decode('utf-8')
        df = await asyncio.to_thread(pd.read_csv, io.StringIO(file_content_str))
        data_summary = await asyncio.to_thread(get_data_summary, df)
    
    except Exception as e:
        error_msg = f"在文件加载或解析阶段发生错误: {e}"
        logging.error(error_msg, exc_info=True)
        
        # 使用 interrupt() 暂停并等待用户输入
        user_response = interrupt(error_msg)
        new_message = HumanMessage(content=user_response)
        
        return {"messages": [new_message], "fold_decision": "agent"}

    ## 优化：只保存 file_content 和摘要，不保存 DataFrame
    # 原因：DataFrame 序列化体积大，file_content 可随时重新生成 DataFrame
    state['file_content'] = file_content_str
    # state['dataframe'] = df  # 避免序列化开销
    state['analysis_parameters'] = data_summary
    
    # 运行确定性验证
    is_ready, issues, recommends = await asyncio.to_thread(
        validate_analysis,
        data_summary, 
        target=target,
        treatment=treatment,
    )

    # 根据验证结果决策
    if is_ready == 0 or is_ready == 1:
        logging.info("验证通过，进入预处理节点。")
        state['analysis_parameters'].update({"target": target, "treatment": treatment})

        # 收集需要返回的新消息
        new_messages = []
        recommend_message = AIMessage(content = "决策：信息完备，进入预处理节点。", name="fold")
        new_messages.append(recommend_message)

        # 针对建议，生成提示
        if recommends:
            recommend_message = AIMessage(content=f"决策：信息完备，进入预处理节点。提示：\n- {recommends}")
            new_messages.append(recommend_message)
        
        return {"messages": new_messages, 
                "analysis_parameters": state['analysis_parameters'], 
                "fold_name": state['fold_name'], 
                "file_content": state['file_content'],
                "tool_call_request": False,
                "fold_decision": "preprocess",
                }
    
    else:
        logging.warning(f"验证失败，需要人工干预。原因: {', '.join(issues)}")
        
        # 对于issue中有存在变量缺失的情况的，进行修正询问，对于数据有问题，进行数据补充询问
        has_param_issue = any("目标变量" in issue or "处理变量" in issue for issue in issues)
        has_data_quality_issue = any("缺失" in issue or "样本量" in issue or "常数列" in issue or "高基数" in issue or "ID列" in issue for issue in issues)

        call_to_action = "请您根据上述问题进行调整。" # 通用备用方案
        if has_param_issue:
            call_to_action = "请您根据上述问题，明确或修正'目标变量'和'处理变量'的指定。"
        elif has_data_quality_issue:
            call_to_action = "您的数据似乎存在一些质量问题。请您考虑对数据进行清洗，或上传一份新的文件。"
        
        columns_list = data_summary.get('columns', [])
        question = (
            "为了开始因果分析，我需要您的帮助来解决以下问题：\n"
            f"- {issues}\n\n"
            f"作为参考，您的数据中包含以下可用列：\n`{', '.join(columns_list)}`\n\n"
            f"**{call_to_action}**"
        )
        
        # interrupt() 会立即暂停节点执行，返回 question 给调用者
        # 当用户提供输入后，interrupt() 会返回用户的输入值
        user_response = interrupt(question)
        
        logging.info(f"用户提供的响应: {user_response}")
        
        # 将用户的响应添加到消息历史，并返回一个路由消息
        # 让 fold_router 知道需要回到 agent 重新判断
        return {
            "messages": [
                HumanMessage(content=user_response),
                AIMessage(content="决策：已收到用户输入，返回 agent 重新判断", name="fold")
            ],
            "fold_name": state['fold_name'],
            "file_content": state['file_content'],
            "analysis_parameters": state['analysis_parameters'],
            "fold_decision": "agent",
        }


async def preprocess_node(state: CausalChatState, llm: ChatOpenAI) -> dict:
    """
    项目预处理模块:
    1.  从状态(state)中加载 DataFrame 和数据摘要。
    2.  调用 `generate_visualizations` 生成数据图表。
        - 如果缺少可视化库 (seaborn, matplotlib)，会跳过此步并向用户发出警告。
    3.  调用 LLM 对数据摘要进行自然语言总结。
    4.  将图表和总结存入状态，然后直接进入下一步。
    """
    logging.info(" 步骤: 数据预处理与分析节点 ")

    # 从 file_content 动态生成 DataFrame
    file_content = state.get("file_content")
    analysis_parameters = state.get("analysis_parameters", {})

    if file_content is None or not analysis_parameters:
        error_msg = "无法执行预处理，因为数据或其摘要信息在状态中丢失。"
        logging.error(error_msg)
        
        user_response = interrupt(error_msg)
        new_message = HumanMessage(content=user_response)
        
        return {"messages": [new_message]}

    # 动态生成 DataFrame（从 file_content）
    df = await asyncio.to_thread(pd.read_csv, io.StringIO(file_content))
    logging.info(f"从 file_content 重新生成 DataFrame，shape: {df.shape}")

    # 生成可视化图表 
    visualizations = {}
    try:
        visualizations = await asyncio.to_thread(generate_visualizations, df, analysis_parameters)
        state["visualizations"] = visualizations
        logging.info("数据可视化图表已成功生成。")
    
    except Exception as e:
        logging.error(f"生成数据可视化时发生未知错误: {e}", exc_info=True)
        # 可视化失败不阻断流程，记录日志即可
        # 不需要添加消息到state，继续执行后续步骤
    
    # 3. 调用LLM进行自然语言总结
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system",
             """
             system role: {system_role}
             mission:
            你的任务是根据提供的数据摘要信息，为即将进行的因果分析撰写一段简洁明了的自然语言总结。

            # 数据摘要信息:
            {data_summary}

            # 你的任务:
            1.  **开篇总结**: 简要说明数据集的规模（行数和列数）。
            2.  **目标变量和处理变量的摘录**: 对输入数据中的“target”和“treatment”进行摘取，并告知用户目前处理的变量是这两个变量。
            3.  **风险提示**: 提及数据中存在的潜在问题，例如高缺失值列、常数列、高基数分类变量或疑似ID列。
            4.  **结论**: 给出一个总体评价，说明数据是否已准备好进行下一步的因果分析。

            请使用清晰、专业的语言，让非技术人员也能理解数据的基本状况。
            """),
            ("human", "请根据上述指示和提供的数据摘要，生成总结报告。")
        ]
    )
    
    
    runnable = prompt | llm | StrOutputParser()
    
    logging.info("正在调用LLM生成数据分析总结...")
    
    
    preprocess_summary = await runnable.ainvoke({
        "data_summary": json.dumps(analysis_parameters, indent=2, ensure_ascii=False),
        "system_role": data_prompt()
    })
    logging.info(f"LLM数据总结结果: {preprocess_summary}")

    # 4. 更新状态并返回新消息
    state["preprocess_summary"] = preprocess_summary
    
    summary_message = AIMessage(
        content= "决策：数据预处理完成，进入工具处理路由",
        name="preprocess"
    )

    # 只返回新消息和需要更新的状态
    return {
        "messages": [summary_message],
        "preprocess_summary": state["preprocess_summary"],
        "visualizations": state.get("visualizations", {})
    }


from Agent.knowledge_base.query_rag import format_rag_summary_for_prompt
from Agent.tool_node.rag_query_task import rag_query_task
from Agent.tool_node.rag_questions import get_rag_questions
from Agent.tool_node.mcp_tool_call_adapter import normalize_mcp_tool_call_message
from Agent.tool_node.tool_message_adapter import (
    attach_tool_call_metadata,
    latest_ai_tool_call_ids,
    latest_matching_tool_result,
    parse_tool_message_json,
)


def _mcp_tool_name(tool: Any) -> str | None:
    """从 MCP/LangChain tool 对象或 OpenAI-style dict 中读取工具名。"""
    if isinstance(tool, dict):
        function = tool.get("function", {})
        return function.get("name") if isinstance(function, dict) else None
    return getattr(tool, "name", None)


def _has_mcp_tool(mcp_tools: list, tool_name: str) -> bool:
    """判断当前 MCP tool 列表是否包含指定工具。"""
    return any(_mcp_tool_name(tool) == tool_name for tool in mcp_tools)


def _explicit_direct_lingam_requested(state: CausalChatState) -> bool:
    """检测用户是否明确要求使用 DirectLiNGAM。"""
    latest_text = _latest_human_text(state)
    normalized = latest_text.lower()
    compact = "".join(char for char in normalized if char.isalnum())
    return any(
        token in normalized
        for token in ("directlingam", "direct lingam", "direct-lingam", "direct_lingam")
    ) or "directlingam" in compact


def _direct_mcp_tool_call(tool_name: str, state: CausalChatState, mcp_tools: list) -> AIMessage:
    """为确定性工具选择构造 ToolNode 可消费的标准 AIMessage。"""
    ai_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": tool_name,
                "args": {},
                "id": f"planner-{tool_name}-1",
                "type": "tool_call",
            }
        ],
    )
    return normalize_mcp_tool_call_message(ai_message, state, mcp_tools)


async def mcp_planner_node(state: CausalChatState, llm: ChatOpenAI, mcp_tools: list) -> dict:
    """强制模型从可用 MCP tools 中选择一个，并返回标准 Tool Call。"""
    if not mcp_tools:
        raise RuntimeError("No MCP tools are available for causal analysis.")
    if (
        _explicit_direct_lingam_requested(state)
        and _has_mcp_tool(mcp_tools, "causal_direct_lingam")
    ):
        logging.info("检测到明确 DirectLiNGAM 请求，确定性选择 causal_direct_lingam。")
        return {
            "messages": [
                _direct_mcp_tool_call("causal_direct_lingam", state, mcp_tools)
            ]
        }

    # 固定 tool_choice 的请求使用关闭 Thinking 的隔离副本。
    planner_llm = llm.model_copy(
        update={
            "extra_body": {
                **(llm.extra_body or {}),
                "thinking": {"type": "disabled"},
            }
        }
    )
    mcp_llm = planner_llm.bind_tools(
        mcp_tools,
        tool_choice="required",
        parallel_tool_calls=False,
    )
    logging.info("正在启动 MCP 查询生成任务...")

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            """你是 MCP 因果分析工具规划器。

            你的任务是你必须通过 tool call 选择一个最合适的因果分析工具；并且通过 tool calling 协议返回tool_calls
            返回不要普通回答，不要输出 JSON 文本。
            根据用户需求、数据摘要和预处理总结选择工具.""",
        ),
        (
            "human",
            "用户上下文：{messages}\n\n数据摘要：{data_summary}\n\n预处理总结：{preprocess_summary},请完成任务。",
        ),
    ])

    prompt_value = await prompt.ainvoke({
        "messages": llm_prompt_messages(state.get("messages", [])),
        "data_summary": json.dumps(state.get("analysis_parameters", {}), indent=2, ensure_ascii=False),
        "preprocess_summary": state.get("preprocess_summary", ""),
    })
    ai_message = await mcp_llm.ainvoke(prompt_value.to_messages())
    ai_message = normalize_mcp_tool_call_message(ai_message, state, mcp_tools)
    return {"messages": [ai_message]}


async def mcp_result_parser_node(state: CausalChatState) -> dict:
    """解析 MCP ToolNode 产生的 ToolMessage，并把结果注入状态。"""
    messages = state.get("messages", [])
    latest_tool_message, latest_tool_call = latest_matching_tool_result(messages)
    if latest_tool_message is None:
        existing_result = state.get("causal_analysis_result")
        if isinstance(existing_result, dict) and existing_result.get("success") is False:
            return {
                "causal_analysis_result": existing_result,
                "tool_call_request": False,
            }
        return {
            "causal_analysis_result": {
                "success": False,
                "error": "MCP 工具没有返回与本次调用匹配的 ToolMessage。",
                "error_type": "MCPProtocolError",
            },
            "tool_call_request": False,
        }

    parsed = parse_tool_message_json(latest_tool_message)
    if type(parsed.get("success")) is not bool:
        logging.warning(
            "MCP 返回结果缺少布尔型 success 字段: keys=%s",
            sorted(str(key) for key in parsed),
        )
        parsed = {
            "success": False,
            "error": "MCP 返回结果不符合协议：缺少布尔型 success 字段。",
            "error_type": "MCPProtocolError",
        }
    elif parsed.get("success") is True and set(parsed) == {"success", "data"}:
        logging.warning(
            "MCP 返回结果不是结构化因果分析结果: data_type=%s",
            type(parsed.get("data")).__name__,
        )
        parsed = {
            "success": False,
            "error": "MCP 返回结果不符合协议：未返回结构化因果分析结果。",
            "error_type": "MCPProtocolError",
        }

    result = attach_tool_call_metadata(
        parsed,
        latest_tool_message,
        latest_tool_call,
    )
    return {
        "causal_analysis_result": result,
        "tool_call_request": bool(parsed.get("success")),
    }


async def rag_question_planner_node(state: CausalChatState, llm: ChatOpenAI, rag_tools: list) -> dict:
    """生成 RAG 问题；结构化失败时写入稳定降级结果并跳过工具调用。"""
    logging.info("正在启动 RAG 问题生成任务...")

    max_questions = 3
    try:
        rag_questions = await get_rag_questions(state, llm, max_questions=max_questions)
    except StructuredOutputError as exc:
        logging.warning("RAG 问题生成失败，将跳过知识库工具: %s", exc)
        return {
            "messages": [
                AIMessage(
                    content="知识库问题生成失败，已跳过知识库增强。",
                    name="rag_question_planner",
                )
            ],
            "knowledge_base_result": {
                "success": False,
                "summary": "知识库增强暂不可用，报告将仅基于因果分析结果生成。",
                "questions": [],
                "evidence_count": 0,
                "error": str(exc),
            },
        }
    tool_name = "rag_enrichment_search"
    if rag_tools:
        tool_name = getattr(rag_tools[0], "name", tool_name)

    ai_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": tool_name,
                "args": {
                    "questions": rag_questions,
                    "max_results": 5,
                },
                "id": "rag_enrichment_search_1",
            }
        ],
    )
    return {"messages": [ai_message]}


async def rag_result_parser_node(state: CausalChatState) -> dict:
    """子节点：获取rag返回内容，注入state当中"""
    messages = state.get("messages", [])
    latest_tool_message, latest_tool_call = latest_matching_tool_result(messages)
    if latest_tool_message is None:
        if latest_ai_tool_call_ids(messages):
            return {
                "knowledge_base_result": {
                    "success": False,
                    "summary": "知识库增强暂不可用，报告将仅基于因果分析结果生成。",
                    "questions": [],
                    "evidence_count": 0,
                    "error": "No RAG tool result was produced.",
                }
            }
        existing_result = state.get("knowledge_base_result")
        if isinstance(existing_result, dict):
            return {"knowledge_base_result": existing_result}
        return {
            "knowledge_base_result": {
                "success": False,
                "summary": "知识库增强暂不可用，报告将仅基于因果分析结果生成。",
                "questions": [],
                "evidence_count": 0,
                "error": "No RAG tool result was produced.",
            }
        }

    parsed = parse_tool_message_json(latest_tool_message)
    if not parsed.get("success"):
        parsed.setdefault("summary", "知识库增强暂不可用，报告将仅基于因果分析结果生成。")
        parsed.setdefault("questions", [])
        parsed.setdefault("evidence_count", 0)
    result = attach_tool_call_metadata(
        parsed,
        latest_tool_message,
        latest_tool_call,
    )
    return {
        "knowledge_base_result": result,
    }


# 环路检测模块
from Agent.Postprocessing.cycles_check.detect_cycles import detect_cycles
from Agent.Postprocessing.cycles_check.extract_causal_return import extract_adjacency_matrix
from Agent.Postprocessing.cycles_check.fix_cycles import fix_cycles_with_llm

# 边评估模块
from Agent.Postprocessing.evaluate_edge.evaluate_edge_llm import evaluate_edges_with_llm
from Agent.Postprocessing.evaluate_edge.edge_utils import extract_critical_edges


def _matrix_convention_for_analysis(analysis_result: Dict[str, Any]) -> str:
    """根据显式字段、算法标识或 OLC 元数据确定邻接矩阵方向。"""
    explicit_convention = str(
        analysis_result.get("matrix_convention", "")
    ).strip().lower()
    if explicit_convention in {"target_to_source", "causallearn", "olc"}:
        return explicit_convention

    algorithm = str(analysis_result.get("algorithm", "")).strip().lower()
    raw_results = analysis_result.get("raw_results", {})
    if algorithm == "direct_lingam":
        return "target_to_source"
    if algorithm == "olc" or "coefficient_matrix" in raw_results:
        return "olc"
    return "causallearn"


def _as_revised_graph(
    graph_nodes: List[Dict[str, Any]],
    revised_edges: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """把内部 EdgeRecord 集合序列化成前端可直接渲染的 vis-network 图。"""
    vis_edges = []
    for edge in revised_edges:
        edge_type = edge.get("edge_type", "directed")
        if edge_type == "bidirected":
            arrows = "to,from"
        elif edge_type in {"directed", "partially_oriented"}:
            arrows = "to"
        else:
            arrows = ""

        vis_edges.append(
            {
                "from": edge["source"],
                "to": edge["target"],
                "arrows": arrows,
                "dashes": edge_type in {"undirected", "partially_oriented"},
                "label": edge.get("label", ""),
            }
        )

    return {"nodes": list(graph_nodes), "edges": vis_edges}


def _without_removed_edges(
    candidate_edges: List[Dict[str, Any]],
    removed_edges: List[Tuple[str, str]],
) -> List[Dict[str, Any]]:
    """从 LLM 边评估候选中排除已经由环路修复真实删除的边。"""
    removed_keys = set(removed_edges)
    return [
        edge
        for edge in candidate_edges
        if (edge.get("source"), edge.get("target")) not in removed_keys
    ]


async def postprocess_node(state: CausalChatState, llm: ChatOpenAI) -> dict:
    """
    后处理模块：
    1. 提取并验证因果图结构
    2. 环路检测和修正
    3. LLM辅助评估关键边的合理性
    4. 准备修正记录和格式化数据供报告使用
    
    技术说明：
        - 使用networkx进行图结构分析
        - 使用LLM进行环路修正和边评估决策
        - 所有修正操作都会被详细记录
    """
    logging.info(" 步骤: 后处理节点 ")
    
    try:
        # 提取原始因果图
        analysis_result = state["causal_analysis_result"]
        adjacency_matrix, node_names = extract_adjacency_matrix(analysis_result)
        
        # 如果提取失败，返回错误
        if adjacency_matrix.size == 0:
            error_msg = "无法从分析结果中提取有效的因果图数据。"
            logging.error(error_msg)
            # 只返回新消息和错误状态
            return {
                "messages": [AIMessage(content=f"决策：{error_msg}", name="postprocess")],
                "postprocess_result": {"error": error_msg}
            }
        
        logging.info(f"提取到 {len(node_names)} 个节点的因果图")
        
        # 创建原始图的副本用于修正
        working_matrix = adjacency_matrix.copy()
        matrix_convention = _matrix_convention_for_analysis(analysis_result)
        cycle_removed_edges: List[Tuple[str, str]] = []
        
        # 环路检测和修正
        has_cycle, cycles = detect_cycles(
            working_matrix,
            node_names,
            matrix_convention=matrix_convention,
        )
        if has_cycle:
            logging.info(f"检测到 {len(cycles)} 个环路，开始LLM辅助修正...")
            working_matrix, cycle_removed_edges = await asyncio.to_thread(
                fix_cycles_with_llm,
                working_matrix, 
                cycles, 
                node_names,
                llm, 
                state,
                matrix_convention=matrix_convention,
            )
            # 再次检测以确认环路已被消除
            has_cycle_after, _ = detect_cycles(
                working_matrix,
                node_names,
                matrix_convention=matrix_convention,
            )
            if has_cycle_after:
                logging.warning("警告：部分环路仍然存在，可能需要人工干预。")

            else:
                logging.info("所有环路已成功修正！")
        
        # LLM评估关键边
        critical_edges, edge_debug_info = extract_critical_edges(analysis_result)
        logging.info(
            "边评估候选提取结果: source=%s, count=%s, input_type=%s, algorithm=%s, reason=%s",
            edge_debug_info.get("source"),
            edge_debug_info.get("candidate_edge_count"),
            edge_debug_info.get("input_type"),
            edge_debug_info.get("algorithm"),
            edge_debug_info.get("reason"),
        )
        candidate_edge_count = edge_debug_info.get("candidate_edge_count", 0)
        normalized_edge_count = edge_debug_info.get("normalized_edge_count", 0)
        if candidate_edge_count != normalized_edge_count:
            error_msg = (
                "因果边结构校验失败："
                f"候选边 {candidate_edge_count} 条，仅成功规范化 {normalized_edge_count} 条。"
            )
            logging.error(error_msg)
            return {
                "messages": [
                    AIMessage(
                        content=f"后处理遇到问题: {error_msg}\n\n将使用原始分析结果继续生成报告。",
                        name="postprocess",
                    )
                ],
                "postprocess_result": {
                    "error": error_msg,
                    "original_graph": analysis_result.get("data", {}),
                    "edge_evaluation_debug": edge_debug_info,
                },
            }
        critical_edges = _without_removed_edges(critical_edges, cycle_removed_edges)
        
        edge_evaluations: Dict[str, Any] = {}
        if critical_edges:
            logging.info(f"识别到 {len(critical_edges)} 条关键边，开始LLM评估...")
            edge_evaluations = await asyncio.to_thread(evaluate_edges_with_llm, critical_edges, state, llm)
        else:
            logging.info("未识别到需要评估的关键边")
            edge_evaluations = {
                "schema_version": "edge_evaluation_v2",
                "decisions": [],
                "revised_edges": [],
                "revision_summary": "",
                "confidence": "low",
            }

        serialized_cycle_removals = [
            {"source": source, "target": target}
            for source, target in cycle_removed_edges
        ]
        edge_evaluations = {
            **edge_evaluations,
            "cycle_removed_edges": serialized_cycle_removals,
        }
        
        
        revised_edges = edge_evaluations.get(
            "revised_edges",
            edge_evaluations.get("decision", []),
        )
        revision_summary = edge_evaluations.get(
            "revision_summary",
            edge_evaluations.get("reason", ""),
        )
        if cycle_removed_edges:
            cycle_summary = "环路修订删除边：" + "、".join(
                f"{source} -> {target}" for source, target in cycle_removed_edges
            )
            revision_summary = "；".join(
                summary for summary in (cycle_summary, revision_summary) if summary
            )

        # 准备结构化输出
        postprocess_result = {
            "original_graph": state["causal_analysis_result"].get("data", {}),
            "revised_graph": _as_revised_graph(
                analysis_result.get("data", {}).get("nodes", []),
                revised_edges,
            ),
            "revision_summary": revision_summary,
            "edge_evaluation": edge_evaluations,
            "edge_evaluation_debug": {
                **edge_debug_info,
                "ran": bool(critical_edges),
                "schema_version": edge_evaluations.get("schema_version", ""),
                "decision_count": len(edge_evaluations.get("decisions", [])),
                "revised_edge_count": len(revised_edges),
                "cycle_removed_count": len(cycle_removed_edges),
                "confidence": edge_evaluations.get("confidence", ""),
            },
            "had_cycles": has_cycle,
            "num_cycles_fixed": len(cycle_removed_edges),
            "matrix_convention": matrix_convention,
        }
        
        state["postprocess_result"] = postprocess_result
        
        
        # 收集需要返回的新消息
        new_messages = []
        
        # 如果有环路被修正，添加额外说明
        if has_cycle:
            explanation = f"\n\n**注意**：原始图中检测到 {len(cycles)} 个环路，部分已通过LLM辅助决策进行修正。理由如下：{revision_summary}"
            new_messages.append(AIMessage(content=explanation, name="postprocess"))
        
        new_messages.append(AIMessage(
            content="决策：后处理完成，准备进入报告生成阶段",
            name="postprocess"
        ))

        logging.info("后处理完成，准备进入报告生成阶段")
        
        # 只返回新消息和后处理结果
        return {
            "messages": new_messages,
            "postprocess_result": state["postprocess_result"]
        }
        
    except Exception as e:
        postprocess_result = {"error": str(e) + f"\n\n将使用原始分析结果继续生成报告。"}
        # 异常处理：记录错误但不中断流程
        error_message = AIMessage(
            content=f"后处理遇到问题: {str(e)}\n\n将使用原始分析结果继续生成报告。",
            name="postprocess"
        )
        
        # 只返回新消息和错误状态
        return {
            "messages": [error_message],
            "postprocess_result": postprocess_result
        }

## 调用元数据
from Agent.Report.Metadata_sum import metadata_summary, metadata_mapping


def _causal_method_context_for_report(analysis_result: Dict[str, Any]) -> str:
    """为报告节点生成算法专用解释边界，避免 LLM 从原始 dict 中遗漏关键假设。"""
    if not isinstance(analysis_result, dict):
        return "No structured causal analysis result is available."

    algorithm = str(analysis_result.get("algorithm", "")).strip().lower()
    if algorithm != "direct_lingam":
        return "No additional algorithm-specific reporting guidance is required."

    implementation = analysis_result.get("implementation", {})
    parameters = analysis_result.get("parameters", {})
    raw_results = analysis_result.get("raw_results", {})
    diagnostics = analysis_result.get("diagnostics", {})

    causal_order_names = raw_results.get("causal_order_names", [])
    if isinstance(causal_order_names, list) and causal_order_names:
        causal_order_text = " -> ".join(str(name) for name in causal_order_names)
    else:
        causal_order_text = "not available"

    return (
        "DirectLiNGAM reporting guidance:\n"
        f"- Implementation: causal-learn {implementation.get('version', 'unknown')} "
        f"with embedded LiNGAM {implementation.get('embedded_version', 'unknown')}.\n"
        f"- Parameters: measure={parameters.get('measure', 'unknown')}.\n"
        f"- Samples/features: n_samples={diagnostics.get('n_samples', 'unknown')}, "
        f"n_features={diagnostics.get('n_features', 'unknown')}.\n"
        f"- Matrix convention: {analysis_result.get('matrix_convention', 'target_to_source')}; "
        "B[target, source] means source -> target.\n"
        f"- Estimated causal order: {causal_order_text}.\n"
        "- Required assumptions: continuous numeric variables, linear structural equation model, "
        "non-Gaussian and mutually independent errors, acyclic causal graph, and no unmodeled "
        "latent confounders among the observed variables.\n"
        "- Interpretation rule: describe weighted directed edges as candidate causal relations under "
        "these assumptions, not as experimentally verified causal facts. If assumptions are not "
        "justified by domain knowledge, explicitly state this limitation."
    )


async def report_node(state: CausalChatState, llm: ChatOpenAI) -> dict:
    """
    报告模块：
    主要是对所有的参数生成一份报告
    
    """
    logging.info(" 步骤: 报告模块 ")
    # 分离 system prompt 和 messages placeholder
    system_prompt_template = (
        """
         system role: {system_role}
         #输出语言：**请用英文回复**
         
         你的任务是根据用户的对话历史和当前状态，按照要求的报告格式生成一份综合的，完整的因果领域报告
         # 当前状态摘要
         1. 预处理结果：{preprocess_summary}
         2. 预处理元数据：{preprocess_meta_data}
         2. 因果分析结果：{causal_analysis_result}
        3. 知识库结果：{knowledge_base_result}
        4. 后处理结果：{postprocess_result}
        5. 算法解释补充：{method_context}

        ## 因果分析结果解读规则
        - 如果因果分析结果包含 error_type，请明确说明算法未能产生有效因果图，不要声称“没有因果关系”。
        - 如果因果分析结果包含 fallback_from 和 fallback_reason，请说明原算法不适用并已改用 fallback_tool 的结果。
        - 只有当算法 success 为 true 且边列表为空时，才可以表述为“未发现显著因果边/因果关系”。
        - 如果算法解释补充中出现 DirectLiNGAM，请在方法说明或局限性中明确写出线性、非高斯、误差独立、DAG 和无潜在混杂等假设。
        - DirectLiNGAM 的带权边只能解释为模型假设下的候选因果关系，不得写成实验已验证事实。
         
        ## 报告结构要求
        1. **数据概览**：基于上述数据概览进行总结

        2. **数据可视化**：在合适的位置插入图表，帮助读者理解数据分布
            - 如果用户没有提到具体的变量类型，必须插入所有变量的图表，变量需要从预处理元数据中获取
            - 如果用户提到了具体的变量类型，则只插入该变量的图表，变量类型需要从预处理元数据中获取
        3. **分析过程**：详细描述因果分析的步骤和方法
        4. **分析结果**：总结主要发现和因果关系

        ## 图表插入规则
        - 当你想要插入某个图表时，直接在文本中使用对应的占位符(占位符见预处理元数据)
        - 例如：要展示年龄分布，就写 [[CHART:histogram_age]]
        - 占位符需要单独成行，前后空一行
        - 在占位符前后添加必要的文字说明，解释这个图表展示了什么
        ### 示例格式:
        #### 年龄分布特征
        从收集的数据来看，用户年龄主要集中在...

        [[CHART:histogram_age]]

        上图展示了年龄的分布情况，我们可以观察到...、
        """
    )
    
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt_template),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    # 格式化字符串输出
    runnable = prompt | llm | StrOutputParser()
    
    meta_data = await asyncio.to_thread(
        metadata_summary,
        state.get("analysis_parameters", {}),
        state.get("visualizations", {}),
    )
    mapping_data = await asyncio.to_thread(
        metadata_mapping,
        meta_data,
        state.get("visualizations", {}),
    )
    
    # 在invoke时，将模板变量和消息历史分开传入
    knowledge_summary = format_rag_summary_for_prompt(
        state.get("knowledge_base_result", {}),
        max_questions=3,
        include_evidence=True
    )

    response = await runnable.ainvoke({
        "messages": llm_prompt_messages(state["messages"]),
        "preprocess_meta_data": meta_data,
        "preprocess_summary": state.get("preprocess_summary", {}),
        "causal_analysis_result": state.get("causal_analysis_result", {}),
        "knowledge_base_result": knowledge_summary,
        "postprocess_result": state.get("postprocess_result", {}),
        "method_context": _causal_method_context_for_report(
            state.get("causal_analysis_result", {})
        ),
        "system_role": causal_report_prompt()
    })

    logging.info(f"LLM报告结果: {response}")

    report_complete_message = AIMessage(
        content="决策：因果分析报告已生成完成。",
        name="report"
    )
    # 占位符替换：将报告中的占位符替换为实际的 HTML 图片标签

    ## 注释:避免数据库中存入最终报告的html图片标签，导致数据库爆炸
    # final_report = response
    # try:
    #     for placeholder, base64_str in mapping_data.items():

    #         html_img = f'<img src="data:image/png;base64,{base64_str}" alt="{placeholder}" style="max-width:100%; height:auto; display:block; margin:20px 0;" />'
    #         final_report = final_report.replace(placeholder, html_img)
        
    #     logging.info(f"成功替换了 {len(mapping_data)} 个图表占位符")
    # except Exception as e:
    #     logging.error(f"替换图表占位符时发生错误: {e}", exc_info=True)
    #     # 如果替换失败，仍然返回原始报告（不含图片）
    #     final_report = response
    # 只返回新消息和最终报告
    return {
        "final_report": response,  
        "visualization_mapping": mapping_data,
        "messages": [report_complete_message]
    }

async def normal_chat_node(state: CausalChatState,llm: ChatOpenAI) -> dict:
    """
    Represents "正常问答".
    This is for when the agent determines it's a simple chat conversation.
    """
    logging.info(" 步骤: 普通问答节点 ")
    
    prompt_template = (
        """
        system role: 你是日常聊天助手，你的任务是根据用户的对话历史，回答用户的问题。
        
        """
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", prompt_template),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )
    runnable = prompt | llm | StrOutputParser()
    response = await runnable.ainvoke({
        "messages": llm_prompt_messages(state["messages"]),
    })
    # 只返回新消息
    return {"messages": [AIMessage(content=response, name="normal_chat")]}

async def inquiry_answer_node(state: CausalChatState, llm: ChatOpenAI) -> dict:
    """
    根据报告追问用户的问题
    """
    logging.info(" 步骤: 根据报告回答用户的问题节点 ")
    prompt_template = (
        """
        system role: {system_role}
        # 当前状态摘要
        1. 因果分析结果：{causal_analysis_result}
        2. 知识库结果：{knowledge_base_result}
        3. 后处理结果：{postprocess_result}
        4. 报告：{final_report}
        
        # 你的任务：根据历史摘要和所有分析结果，回答用户问题
        - 用户的问题：{messages}
        
        """
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", prompt_template),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )
    runnable = prompt | llm | StrOutputParser()
    knowledge_summary = format_rag_summary_for_prompt(
        state.get("knowledge_base_result", {}),
        max_questions=2,
        include_evidence=True
    )

    response = await runnable.ainvoke({
        "messages": llm_prompt_messages(state["messages"]),
        "causal_analysis_result": state.get("causal_analysis_result", {}),
        "knowledge_base_result": knowledge_summary,
        "postprocess_result": state.get("postprocess_result", {}),
        "final_report": state.get("final_report", {}),
        "system_role": causal_prompt()
    })
    # 只返回新消息
    return {"messages": [AIMessage(content=response, name="inquiry_answer")]}
