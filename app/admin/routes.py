"""管理员只读接口与受保护后台页面路由。"""

from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory
import logging

from Database.inspection import MAX_SLOW_QUERY_LIMIT
from Database.monitoring import (
    DEFAULT_REFRESH_GROUPS,
    get_dashboard_snapshots,
    get_database_overview_snapshot,
    get_db_health,
    get_integrity_snapshot,
    get_sql_performance_snapshot,
    get_worker_snapshot_from_cache,
    request_snapshot_refresh,
)
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
    """从共享快照返回 revision、节点、连接和表容量事实。"""
    return jsonify({"success": True, "data": get_database_overview_snapshot()})


@admin_bp.route("/db/dashboard")
@admin_required
def db_dashboard():
    """一次返回看板所需的全部共享快照和服务端刷新策略。"""
    return jsonify({"success": True, "data": get_dashboard_snapshots()})


@admin_bp.route("/db/refresh", methods=["POST"])
@admin_required
def db_refresh():
    """登记实时、SQL 性能和容量快照的共享手动刷新请求。"""
    try:
        requested = request_snapshot_refresh(DEFAULT_REFRESH_GROUPS)
        return jsonify({"success": True, "data": requested}), 202
    except Exception as exc:
        logging.error("登记数据库看板刷新请求失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "登记数据库看板刷新请求失败"}), 500


@admin_bp.route("/db/integrity")
@admin_required
def db_integrity():
    """返回最近一次运行期完整性审计共享快照。"""
    mode = request.args.get("mode", "quick")
    if mode != "quick":
        return jsonify({"success": False, "error": "mode 仅支持 quick"}), 400
    return jsonify({"success": True, "data": get_integrity_snapshot()})


@admin_bp.route("/db/integrity/run", methods=["POST"])
@admin_required
def db_integrity_run():
    """登记独立完整性审计请求，不受定时审计开关限制。"""
    try:
        requested = request_snapshot_refresh(("integrity",))
        return jsonify({"success": True, "data": requested}), 202
    except Exception as exc:
        logging.error("登记数据库完整性审计请求失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "登记数据库完整性审计请求失败"}), 500


@admin_bp.route("/db/slow-queries")
@admin_required
def db_slow_queries():
    """从共享快照返回 SQL 性能摘要，并保留旧慢查询字段。"""
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
        return jsonify({"success": True, "data": get_sql_performance_snapshot(limit=limit)})
    except Exception as exc:
        logging.error("读取慢查询摘要失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": "读取慢查询摘要失败"}), 500


@admin_bp.route("/jobs/workers")
@admin_required
def job_workers():
    """从实时共享快照返回 worker 与任务状态。"""
    try:
        report = get_worker_snapshot_from_cache()
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
