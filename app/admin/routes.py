"""管理员只读接口与受保护后台页面路由。"""

from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory
import logging

from Database.inspection import (
    MAX_SLOW_QUERY_LIMIT,
    get_database_overview,
    get_quick_integrity_report,
)
from Database.monitoring import get_db_health, get_slow_query_summary
from app.agent.job_service import get_worker_snapshot_report
from app.auth.authorization import admin_required


admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")
admin_page_bp = Blueprint("admin_page", __name__, url_prefix="/admin")
ADMIN_PAGE_DIR = Path(__file__).resolve().parent


@admin_page_bp.route("/database")
@admin_required
def database_dashboard_page():
    """仅向实时校验通过的管理员返回数据库看板 HTML。"""
    return send_from_directory(ADMIN_PAGE_DIR, "db_admin.html")


@admin_bp.route("/db/health")
@admin_required
def db_health():
    """返回仅管理员可读的数据库健康状态。"""
    try:
        return jsonify({"success": True, "data": get_db_health()})
    except Exception as exc:
        logging.error("读取数据库健康状态失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "读取数据库健康状态失败"}), 500


@admin_bp.route("/db/overview")
@admin_required
def db_overview():
    """返回看板首屏所需的 revision、节点、连接和表容量事实。"""
    return jsonify({"success": True, "data": get_database_overview()})


@admin_bp.route("/db/integrity")
@admin_required
def db_integrity():
    """返回主库强一致读取的快速完整性检查结果。"""
    mode = request.args.get("mode", "quick")
    if mode != "quick":
        return jsonify({"success": False, "error": "mode 仅支持 quick"}), 400
    return jsonify({"success": True, "data": get_quick_integrity_report()})


@admin_bp.route("/db/slow-queries")
@admin_required
def db_slow_queries():
    """返回仅管理员可读的慢查询摘要。"""
    raw_limit = request.args.get("limit", "20")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "limit 必须是整数"}), 400
    if not 1 <= limit <= MAX_SLOW_QUERY_LIMIT:
        return jsonify({
            "success": False,
            "error": f"limit 必须在 1 到 {MAX_SLOW_QUERY_LIMIT} 之间",
        }), 400
    try:
        return jsonify({"success": True, "data": get_slow_query_summary(limit=limit)})
    except Exception as exc:
        logging.error("读取慢查询摘要失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "读取慢查询摘要失败"}), 500


@admin_bp.route("/jobs/workers")
@admin_required
def job_workers():
    """返回仅管理员可读的 worker 与任务快照。"""
    try:
        report = get_worker_snapshot_report()
        return jsonify({
            "success": True,
            "data": report["jobs"],
            "summary": report["summary"],
            "meta": {
                key: report[key]
                for key in (
                    "status",
                    "observed_at",
                    "source_role",
                    "source_alias",
                    "is_estimate",
                    "warning",
                )
            },
        })
    except Exception as exc:
        logging.error("读取 worker 任务状态失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "读取 worker 任务状态失败"}), 500
