"""
RAG评测管理路由 —— 面向开发者的HTTP API。
"""
import json
import logging
import math
from flask import Blueprint, jsonify, request, Response

from app.rag_eval.service import (
    get_rag_eval_status,
    get_rag_eval_config,
    get_production_rag_config,
    publish_current_config_to_production,
    update_rag_eval_config,
    run_pipeline_async,
    get_pipeline_runtime_state,
    get_latest_results,
    list_runs,
    list_runs_page,
    delete_run,
    get_run_detail,
    get_latest_analysis,
    get_run_analysis,
    get_run_diff,
    subscribe_progress,
    unsubscribe_progress,
    get_step_descriptions,
    request_pipeline_cancel,
    current_event_timestamp,
)

rag_eval_bp = Blueprint("rag_eval", __name__, url_prefix="/api/rag_eval")


def _json_response(data, status=200):
    """统一JSON响应格式。"""
    return jsonify(_json_safe(data)), status


def _json_safe(value):
    """把 NaN/Infinity 转成 null，避免浏览器 JSON.parse 失败。"""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


# ---- 状态与配置 ----

@rag_eval_bp.route("/status", methods=["GET"])
def api_status():
    """获取当前benchmark、向量库和最新评测的汇总状态。"""
    try:
        return _json_response({"success": True, "data": get_rag_eval_status()})
    except Exception as exc:
        logging.error("获取RAG评测状态失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/config", methods=["GET"])
def api_get_config():
    """获取所有可调参数，按类别分组（retrieval_profile / ragas / pipeline）。"""
    try:
        return _json_response({"success": True, "data": get_rag_eval_config()})
    except Exception as exc:
        logging.error("获取RAG评测配置失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/config", methods=["PUT"])
def api_update_config():
    """更新运行时可调参数（内存中生效，restart后恢复默认）。"""
    try:
        overrides = request.get_json(silent=True) or {}
        result = update_rag_eval_config(overrides)
        return _json_response({"success": True, "data": result})
    except Exception as exc:
        logging.error("更新RAG评测配置失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/production-config", methods=["GET"])
def api_get_production_config():
    """获取正式 RAG 调用当前使用的检索配置。"""
    try:
        return _json_response({"success": True, "data": get_production_rag_config()})
    except Exception as exc:
        logging.error("获取正式RAG配置失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/production-config/publish", methods=["POST"])
def api_publish_production_config():
    """把当前评测检索配置发布为正式 RAG 调用配置。"""
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response({"success": True, "data": publish_current_config_to_production(payload)})
    except Exception as exc:
        logging.error("发布正式RAG配置失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/steps", methods=["GET"])
def api_step_descriptions():
    """返回pipeline各步骤的中文描述。"""
    return _json_response({"success": True, "data": get_step_descriptions()})


# ---- Pipeline 运行 ----

@rag_eval_bp.route("/run", methods=["POST"])
def api_run_pipeline():
    """触发完整pipeline，返回run_id供前端订阅SSE。"""
    try:
        overrides = request.get_json(silent=True) or {}
        result = run_pipeline_async(overrides)
        return _json_response({"success": True, "data": result})
    except Exception as exc:
        logging.error("触发RAG评测pipeline失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/run-state", methods=["GET"])
def api_run_state():
    """获取当前进程内pipeline运行状态，用于页面刷新后恢复运行页。"""
    try:
        run_id = request.args.get("run_id")
        return _json_response({"success": True, "data": get_pipeline_runtime_state(run_id)})
    except Exception as exc:
        logging.error("获取RAG评测运行状态失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs/<run_id>/stream", methods=["GET"])
def api_stream_progress(run_id):
    """SSE端点：订阅某个run的实时进度。"""
    q = subscribe_progress(run_id)

    def generate():
        try:
            # 发送初始连接确认
            connected_event = {
                "type": "connected",
                "message": "SSE连接已建立",
                "timestamp": current_event_timestamp(),
                "run_id": run_id,
            }
            yield f"data: {json.dumps(_json_safe(connected_event), ensure_ascii=False, allow_nan=False)}\n\n"
            while True:
                try:
                    event = q.get(timeout=30)
                    yield f"data: {json.dumps(_json_safe(event), ensure_ascii=False, allow_nan=False)}\n\n"
                    if event["type"] in ("pipeline_done", "pipeline_error", "pipeline_closed"):
                        break
                except Exception:
                    # 超时发送心跳
                    yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False, allow_nan=False)}\n\n"
        except GeneratorExit:
            pass
        finally:
            unsubscribe_progress(run_id)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@rag_eval_bp.route("/runs/<run_id>/cancel", methods=["POST"])
def api_cancel_pipeline(run_id):
    """请求温和取消某个正在运行的pipeline。"""
    try:
        result = request_pipeline_cancel(run_id)
        if result.get("status") == "not_found":
            return _json_response({"success": False, "error": "run not found"}, 404)
        return _json_response({"success": True, "data": result})
    except Exception as exc:
        logging.error("取消RAG评测pipeline失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


# ---- 结果查询 ----

@rag_eval_bp.route("/results/latest", methods=["GET"])
def api_latest_results():
    """获取最新评测结果（retrieval / ragas / claim / trace 各阶段指标）。"""
    try:
        return _json_response({"success": True, "data": get_latest_results()})
    except Exception as exc:
        logging.error("获取最新评测结果失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/analysis/latest", methods=["GET"])
def api_latest_analysis():
    """获取最新评测的报告、trace索引和坏例明细。"""
    try:
        return _json_response({"success": True, "data": get_latest_analysis()})
    except Exception as exc:
        logging.error("获取最新RAG分析数据失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs", methods=["GET"])
def api_list_runs():
    """列出历史run记录。"""
    try:
        page = request.args.get("page", type=int)
        page_size = request.args.get("page_size", type=int)
        if page is None and page_size is None:
            return _json_response({"success": True, "data": list_runs()})
        return _json_response({"success": True, "data": list_runs_page(page or 1, page_size or 10)})
    except Exception as exc:
        logging.error("列出历史run失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs/<run_id>", methods=["GET"])
def api_run_detail(run_id):
    """获取某个run的详细信息（含配置快照）。"""
    try:
        data = get_run_detail(run_id)
        if "error" in data:
            return _json_response({"success": False, "error": data["error"]}, 404)
        return _json_response({"success": True, "data": data})
    except Exception as exc:
        logging.error("获取run详情失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs/<run_id>", methods=["DELETE"])
def api_delete_run(run_id):
    """删除某个历史run目录及其本地output/runs文件。"""
    try:
        data = delete_run(run_id)
        if data.get("status") == "deleted":
            return _json_response({"success": True, "data": data})
        if data.get("status") == "not_found":
            return _json_response({"success": False, "error": "run not found", "data": data}, 404)
        if data.get("status") == "running":
            return _json_response({"success": False, "error": data.get("message") or "run is still running", "data": data}, 409)
        return _json_response({"success": False, "error": data.get("message") or "invalid run_id", "data": data}, 400)
    except Exception as exc:
        logging.error("删除历史run失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs/<run_id>/analysis", methods=["GET"])
def api_run_analysis(run_id):
    """获取某个run的报告、trace索引和坏例明细。"""
    try:
        data = get_run_analysis(run_id)
        if "error" in data:
            return _json_response({"success": False, "error": data["error"]}, 404)
        return _json_response({"success": True, "data": data})
    except Exception as exc:
        logging.error("获取run分析数据失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs/diff", methods=["GET"])
def api_run_diff():
    """对比两个run的关键指标、坏例和配置变化。"""
    try:
        base_run_id = request.args.get("base_run_id")
        candidate_run_id = request.args.get("candidate_run_id")
        return _json_response({"success": True, "data": get_run_diff(base_run_id, candidate_run_id)})
    except Exception as exc:
        logging.error("获取run对比失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)
