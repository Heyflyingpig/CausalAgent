"""因果分析 MCP server；通过 Job 冻结身份读取 MySQL 文件正文。"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(AGENT_DIR)
for path in (PROJECT_ROOT, AGENT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from mcp.server.fastmcp import FastMCP

from Agent.causal.causalachieve import (
    run_direct_lingam_analysis,
    run_olc_analysis,
    run_pc_analysis,
)
from Database.agent_connect import require_frozen_file_for_job


log_file_path = os.path.join(CURRENT_DIR, "mcp_server.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_file_path, encoding="utf-8")],
)

mcp = FastMCP("causal-analyzer")


def _load_csv(
    user_id: int,
    job_id: str,
    input_user_file_id: int,
    input_object_id: int,
) -> str:
    """按可信运行时身份读取 Job  BLOB，仅在 MCP 进程内存中解码。"""
    file_row = require_frozen_file_for_job(
        user_id,
        job_id,
        input_user_file_id,
        input_object_id,
    )
    return file_row["file_content"].decode("utf-8")


def _error_result(message: str, error_type: str) -> dict[str, Any]:
    """构造不包含文件正文或异常原文的 MCP 失败结果。"""
    return {
        "success": False,
        "message": message,
        "error_type": error_type,
    }


@mcp.tool()
async def causal_pc(
    user_id: int,
    job_id: str,
    input_user_file_id: int,
    input_object_id: int,
) -> dict:
    """
    使用PC算法对CSV数据执行因果发现分析。

    PC算法是一种基于约束的因果发现方法，通过测试条件独立性关系构建因果图，
    而不对因果机制的功能形式做出假设。

    算法运行分为两个阶段：
    1. 骨架学习(Skeleton Learning): 通过移除条件独立变量之间的边来构建无向图骨架
    2. 边定向(Edge Orientation): 使用碰撞检测(规则0)和Meek定向规则来定向边，
       生成部分有向无环图(PDAG)

    PC算法特别适用于以下场景：
    - 无需对功能形式进行先验知识的一般性因果发现
    - 仅提供条件独立性信息的场景
    - 使用快速邻接搜索优化的大规模问题


    Args:
        user_id: 由 Agent runtime 注入的当前用户 ID。
        job_id: 由 Agent runtime 注入的当前分析任务 ID。
        input_user_file_id: Job 创建时冻结的逻辑文件 ID。
        input_object_id: Job 创建时冻结的不可变文件对象 ID。

    文件正文由工具按 Job 冻结身份从文件库读取，模型不得传入 csv_data。

    Returns:
        一个包含分析结果的结构化字典，包括因果图结构和边的方向信息。
    """

    try:
        csv_data = _load_csv(user_id, job_id, input_user_file_id, input_object_id)
        logging.info("工具 causal_pc 读取文件字节数=%s", len(csv_data.encode("utf-8")))
        return run_pc_analysis(csv_data)
    except FileNotFoundError:
        return _error_result("任务文件不可用", "FrozenFileNotFound")
    except Exception:
        logging.error("causal_pc 执行失败", exc_info=True)
        return _error_result("执行分析时发生内部错误", "AnalysisError")


@mcp.tool()
async def causal_olc(
    user_id: int,
    job_id: str,
    input_user_file_id: int,
    input_object_id: int,
) -> dict:
    """
    使用OLC算法对CSV数据执行因果发现分析，专门处理存在隐藏混杂因素的场景。

    OLC(Overcomplete Learning for Causal discovery)算法适用于以下场景：
    - 预期存在隐藏混杂因素: 领域知识表明未观测变量影响多个测量变量
    - 虚假相关性存在: 变量之间存在强相关性，但无直接因果关系
    - 函数因果模型: 可以假设因果机制具有加性噪声模型
    - 连续变量: 数据由连续值变量组成（非离散）
    - 足够的样本量: 至少需要几百个样本以进行可靠的四阶累积量估计

    OLC算法不适用于：
    - 没有潜在混杂因素的纯观测场景（请改用PC算法）
    - 离散或分类变量
    - 非加性噪声模型
    - 非常小的样本量（<200个样本）

    Args:
        user_id: 由 Agent runtime 注入的当前用户 ID。
        job_id: 由 Agent runtime 注入的当前分析任务 ID。
        input_user_file_id: Job 创建时冻结的逻辑文件 ID。
        input_object_id: Job 创建时冻结的不可变文件对象 ID。

    文件正文由工具按 Job 冻结身份从文件库读取，模型不得传入 csv_data。

    Returns:
        一个包含分析结果的结构化字典，包括因果图结构和潜在混杂因素信息。
    """
    try:
        csv_data = _load_csv(user_id, job_id, input_user_file_id, input_object_id)
        logging.info("工具 causal_olc 读取文件字节数=%s", len(csv_data.encode("utf-8")))
        return run_olc_analysis(csv_data)
    except FileNotFoundError:
        return _error_result("任务文件不可用", "FrozenFileNotFound")
    except Exception:
        logging.error("causal_olc 执行失败", exc_info=True)
        return _error_result("执行分析时发生内部错误", "AnalysisError")


@mcp.tool()
async def causal_direct_lingam(
    user_id: int,
    job_id: str,
    input_user_file_id: int,
    input_object_id: int,
) -> dict:
    """使用 DirectLiNGAM 对连续数值 CSV 数据执行因果发现分析。

    适用于线性、非高斯、误差独立且无潜在混杂的连续数值变量；文件正文由
    工具按 Job 冻结身份读取，模型不得传入 csv_data。

    Args:
        user_id: 由 Agent runtime 注入的当前用户 ID。
        job_id: 由 Agent runtime 注入的当前分析任务 ID。
        input_user_file_id: Job 创建时冻结的逻辑文件 ID。
        input_object_id: Job 创建时冻结的不可变文件对象 ID。
    """
    try:
        csv_data = _load_csv(user_id, job_id, input_user_file_id, input_object_id)
        logging.info(
            "工具 causal_direct_lingam 读取文件字节数=%s",
            len(csv_data.encode("utf-8")),
        )
        return run_direct_lingam_analysis(csv_data)
    except FileNotFoundError:
        return _error_result("任务文件不可用", "FrozenFileNotFound")
    except Exception:
        logging.error("causal_direct_lingam 执行失败", exc_info=True)
        return _error_result("执行 DirectLiNGAM 分析时发生内部错误", "AnalysisError")


if __name__ == "__main__":
    logging.info("MCP 因果分析服务器启动")
    try:
        mcp.run(transport="stdio")
    except Exception:
        logging.error("MCP 服务器运行时出现致命错误", exc_info=True)
    finally:
        logging.info("MCP 服务器关闭")
