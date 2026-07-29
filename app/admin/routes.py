"""
管理接口路由。
"""

from flask import Blueprint, jsonify
import logging

from Database.monitoring import get_db_health, get_slow_query_summary
from app.agent.job_service import get_worker_snapshot
from app.auth.authorization import admin_required


admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

@admin_bp.route("/db/health")
@admin_required
def db_health():
    """返回仅管理员可读的数据库健康状态。"""
    try:
        return jsonify({"success": True, "data": get_db_health()})
    except Exception as exc:
        logging.error("读取数据库健康状态失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "读取数据库健康状态失败"}), 500


@admin_bp.route("/db/slow-queries")
@admin_required
def db_slow_queries():
    """返回仅管理员可读的慢查询摘要。"""
    try:
        return jsonify({"success": True, "data": get_slow_query_summary()})
    except Exception as exc:
        logging.error("读取慢查询摘要失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "读取慢查询摘要失败"}), 500


@admin_bp.route("/jobs/workers")
@admin_required
def job_workers():
    """返回仅管理员可读的 worker 与任务快照。"""
    try:
        return jsonify({"success": True, "data": get_worker_snapshot()})
    except Exception as exc:
        logging.error("读取 worker 任务状态失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "读取 worker 任务状态失败"}), 500
