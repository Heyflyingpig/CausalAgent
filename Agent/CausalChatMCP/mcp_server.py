import os
import logging
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))      # .../Agent/CausalChatMCP
AGENT_DIR = os.path.dirname(CURRENT_DIR)                      # .../Agent
PROJECT_ROOT = os.path.dirname(AGENT_DIR)                     # 项目根目录

for p in (PROJECT_ROOT, AGENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


from mcp.server.fastmcp import FastMCP
from Agent.causal.causalachieve import (
    run_direct_lingam_analysis,
    run_olc_analysis,
    run_pc_analysis,
)


log_file_path = os.path.join(CURRENT_DIR, 'mcp_server.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
    ]
)
logging.info("MCP Server Script Started, Logging Initialized")


mcp = FastMCP("causal-analyzer")

@mcp.tool()
async def causal_pc(csv_data: str) -> dict:
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

    这是一个纯计算工具，不执行任何数据库或文件系统操作。

    Args:
        csv_data: 一个包含完整CSV文件内容的字符串。

    Returns:
        一个包含分析结果的结构化字典，包括因果图结构和边的方向信息。
    """
    logging.info(f"工具 'causal_pc' 已被调用，输入数据长度: {len(csv_data)}。")
    try:
        # 工具的核心职责：执行分析
        analysis_result = run_pc_analysis(csv_data)
        
        return analysis_result

    except Exception as e:
        logging.error(f"'causal_pc' 工具执行出错: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"执行分析时发生内部错误: {e}",
            "error_type": type(e).__name__,
        }

@mcp.tool()
async def causal_olc(csv_data: str) -> dict:
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

    这是一个纯计算工具，不执行任何数据库或文件系统操作。

    Args:
        csv_data: 一个包含完整CSV文件内容的字符串，数据应为连续值变量。

    Returns:
        一个包含分析结果的结构化字典，包括因果图结构和潜在混杂因素信息。
    """
    logging.info(f"工具 'causal_olc' 已被调用，输入数据长度: {len(csv_data)}。")
    try:
        # 工具的核心职责：执行分析
        analysis_result = run_olc_analysis(csv_data)
        
        return analysis_result
    except Exception as e:
        logging.error(f"'causal_olc' 工具执行出错: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"执行分析时发生内部错误: {e}",
            "error_type": type(e).__name__,
        }


@mcp.tool()
async def causal_direct_lingam(csv_data: str) -> dict:
    """
    使用 DirectLiNGAM 对连续数值 CSV 数据执行因果发现分析。

    DirectLiNGAM 适用于用户明确接受线性、非高斯、误差独立、DAG 且无潜在混杂
    假设的场景。它会返回带权有向无环图、因果顺序和原始系数矩阵；系数矩阵
    采用 B[target, source] 表示 source -> target。

    这是一个纯计算工具，不执行任何数据库或文件系统操作。

    Args:
        csv_data: 一个包含完整 CSV 文件内容的字符串，所有分析列必须为连续数值。

    Returns:
        一个包含 DirectLiNGAM 结构化分析结果或结构化失败信息的字典。
    """
    logging.info(
        "工具 'causal_direct_lingam' 已被调用，输入数据长度: %s。",
        len(csv_data),
    )
    try:
        analysis_result = run_direct_lingam_analysis(csv_data)
        return analysis_result
    except Exception as e:
        logging.error(f"'causal_direct_lingam' 工具执行出错: {e}", exc_info=True)
        return {
            "success": False,
            "algorithm": "direct_lingam",
            "message": f"执行 DirectLiNGAM 分析时发生内部错误: {e}",
            "error_type": type(e).__name__,
        }

if __name__ == "__main__":
    logging.info("MCP 因果分析服务器启动")

    try:
        mcp.run(transport='stdio')
    except Exception as e:
        logging.error(f"MCP 服务器运行时出现致命错误: {e}", exc_info=True)
    finally:
        logging.info("MCP 因果分析服务器关闭") 
