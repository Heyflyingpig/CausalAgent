"""管理员数据库看板、在线配置 API 与 Vue 静态入口。"""

from pathlib import Path

from flask import Blueprint, g, jsonify, redirect, request, send_from_directory
import logging

from Database.inspection import MAX_SLOW_QUERY_LIMIT
from Database.monitor_settings import (
    MonitorSettingsValidationError,
    MonitorSettingsVersionConflict,
    get_monitor_settings,
    reset_monitor_settings,
    save_monitor_settings,
)
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
from app.admin.audit_service import (
    list_monitor_setting_events,
    record_admin_audit_event,
)
from app.auth.authorization import admin_required
from app.auth.csrf import admin_write_required
from app.request_context import get_request_id
from config.settings import settings


admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")
admin_page_bp = Blueprint("admin_page", __name__, url_prefix="/admin")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _admin_dist_dir() -> Path:
    """返回本地或容器内管理员 Vue 构建产物目录。"""
    configured = settings.ADMIN_FRONTEND_DIST_DIR
    return Path(configured) if configured else PROJECT_ROOT / "admin-frontend" / "dist"


def _serve_admin_index():
    """按显式开发配置跳转 Vite，否则返回同源生产 index。"""
    if settings.ADMIN_VITE_DEV_SERVER_URL:
        return redirect(f"{settings.ADMIN_VITE_DEV_SERVER_URL}{request.path}")
    dist_dir = _admin_dist_dir()
    if not (dist_dir / "index.html").is_file():
        logging.error("管理员 Vue 构建产物不存在: %s", dist_dir)
        return jsonify({
            "success": False,
            "error": "管理员前端尚未构建",
            "code": "admin_frontend_missing",
            "request_id": get_request_id(),
        }), 503
    return send_from_directory(dist_dir, "index.html")


@admin_page_bp.route("/database")
@admin_page_bp.route("/database/settings")
@admin_required(page=True)
def database_dashboard_page():
    """仅向实时校验通过的管理员返回 Vue 管理端入口。"""
    return _serve_admin_index()


@admin_page_bp.route("/assets/<path:filename>")
@admin_required(page=True)
def admin_asset(filename: str):
    """仅向实时校验通过的管理员返回 Vue 哈希静态资源。"""
    return send_from_directory(_admin_dist_dir() / "assets", filename)


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
@admin_write_required
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
@admin_write_required
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


def _settings_error(
    *,
    message: str,
    code: str,
    status: int,
    fields: dict | None = None,
    current: dict | None = None,
):
    """构造带 request ID 的稳定监控配置错误响应。"""
    payload = {
        "success": False,
        "error": message,
        "code": code,
        "request_id": get_request_id(),
    }
    if fields is not None:
        payload["fields"] = fields
    if current is not None:
        payload["current"] = current
    return jsonify(payload), status


@admin_bp.route("/db/settings")
@admin_required
def db_settings():
    """返回七项数据库监控覆盖值、有效值、来源和版本。"""
    return jsonify({
        "success": True,
        "data": get_monitor_settings(force_refresh=True),
    })


def _record_failed_setting_write(
    *,
    action: str,
    submitted: object,
    error_code: str,
) -> None:
    """尽力记录配置写入的未处理失败结果。"""
    record_admin_audit_event(
        actor=g.current_user,
        action=action,
        target_type="database_monitor_settings",
        target_id="1",
        old_values=None,
        new_values=submitted,
        result="failed",
        error_code=error_code,
        request_id=get_request_id(),
    )


@admin_bp.route("/db/settings", methods=["PUT"])
@admin_write_required
def db_settings_update():
    """校验乐观版本并在主库事务内保存七项覆盖值。"""
    body = request.get_json(silent=True) or {}
    try:
        data = save_monitor_settings(
            version=body.get("version"),
            overrides=body.get("overrides"),
            actor=g.current_user,
            request_id=get_request_id(),
        )
        return jsonify({"success": True, "data": data})
    except MonitorSettingsValidationError as exc:
        return _settings_error(
            message="数据库监控配置校验失败",
            code="validation_error",
            status=400,
            fields=exc.errors,
        )
    except MonitorSettingsVersionConflict as exc:
        return _settings_error(
            message="配置已被其他管理员修改，请重新加载",
            code="version_conflict",
            status=409,
            current=exc.current,
        )
    except Exception as exc:
        logging.error("保存数据库监控配置失败: %s", exc, exc_info=True)
        _record_failed_setting_write(
            action="db_monitor_settings.update",
            submitted=body.get("overrides"),
            error_code="settings_write_failed",
        )
        return _settings_error(
            message="保存数据库监控配置失败",
            code="settings_write_failed",
            status=500,
        )


@admin_bp.route("/db/settings/reset", methods=["POST"])
@admin_write_required
def db_settings_reset():
    """按乐观版本把全部数据库监控覆盖值重置为空。"""
    body = request.get_json(silent=True) or {}
    try:
        data = reset_monitor_settings(
            version=body.get("version"),
            actor=g.current_user,
            request_id=get_request_id(),
        )
        return jsonify({"success": True, "data": data})
    except MonitorSettingsValidationError as exc:
        return _settings_error(
            message="数据库监控配置校验失败",
            code="validation_error",
            status=400,
            fields=exc.errors,
        )
    except MonitorSettingsVersionConflict as exc:
        return _settings_error(
            message="配置已被其他管理员修改，请重新加载",
            code="version_conflict",
            status=409,
            current=exc.current,
        )
    except Exception as exc:
        logging.error("重置数据库监控配置失败: %s", exc, exc_info=True)
        _record_failed_setting_write(
            action="db_monitor_settings.reset",
            submitted=None,
            error_code="settings_reset_failed",
        )
        return _settings_error(
            message="重置数据库监控配置失败",
            code="settings_reset_failed",
            status=500,
        )


@admin_bp.route("/db/settings/history")
@admin_required
def db_settings_history():
    """有界游标返回数据库监控配置变更记录。"""
    try:
        limit = int(request.args.get("limit", "20"))
        if not 1 <= limit <= 100:
            raise ValueError
    except (TypeError, ValueError):
        return _settings_error(
            message="limit 必须在 1 到 100 之间",
            code="validation_error",
            status=400,
            fields={"limit": "必须在 1 到 100 之间"},
        )
    raw_before_id = request.args.get("before_id")
    try:
        before_id = int(raw_before_id) if raw_before_id is not None else None
        if before_id is not None and before_id < 1:
            raise ValueError
    except (TypeError, ValueError):
        return _settings_error(
            message="before_id 必须是正整数",
            code="validation_error",
            status=400,
            fields={"before_id": "必须是正整数"},
        )
    try:
        return jsonify({
            "success": True,
            "data": list_monitor_setting_events(
                limit=limit,
                before_id=before_id,
            ),
        })
    except Exception as exc:
        logging.error("读取数据库监控配置历史失败: %s", exc, exc_info=True)
        return _settings_error(
            message="读取数据库监控配置历史失败",
            code="settings_history_failed",
            status=500,
        )
