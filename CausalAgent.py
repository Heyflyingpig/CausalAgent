# app.py (Flask后端)
# Agent/MCP 长任务请通过 worker 进程运行。
import os
import logging
import sys

from observability.logging_runtime import configure_logging, current_environment, log_event


configure_logging("web", current_environment(), logging.INFO)

try:
    from config.settings import settings
except (ValueError, FileNotFoundError):
    log_event(
        logging.getLogger(__name__),
        "web.startup.failed",
        details={
            "phase": "configuration",
            "dependency": "settings",
            "reason_code": "initialization_failed",
        },
        exc_info=True,
    )
    sys.exit(1)

try:
    from app import create_app

    app = create_app()
except Exception:
    log_event(
        logging.getLogger(__name__),
        "web.startup.failed",
        details={
            "phase": "application_factory",
            "dependency": "web_runtime",
            "reason_code": "initialization_failed",
        },
        exc_info=True,
    )
    raise SystemExit(1) from None
else:
    log_event(logging.getLogger(__name__), "web.startup.ready")

# 主程序入口
if __name__ == '__main__':
    # 启动 Flask 应用
    #
    # Docker环境注意：
    # - host='0.0.0.0' 监听所有网络接口，允许容器外部访问
    # - host='127.0.0.1' 只允许容器内部访问，Docker端口映射会失效
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
