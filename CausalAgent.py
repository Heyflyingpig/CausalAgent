# app.py (Flask后端)
# Agent/MCP 长任务请通过 worker 进程运行。
import os
import logging
import sys

from observability.logging_runtime import configure_logging, current_environment


configure_logging("web", current_environment(), logging.INFO)

try:
    from config.settings import settings
except (ValueError, FileNotFoundError) as e:
    logging.critical(
        "无法加载应用配置，程序终止",
        extra={
            "event_code": "web.startup.failed",
            "category": "dependency",
            "details": {"reason_code": "configuration_invalid"},
        },
        exc_info=True,
    )
    sys.exit(1)

from app import create_app

app = create_app()
logging.getLogger(__name__).info(
    "Flask Web 层已就绪",
    extra={
        "event_code": "web.startup.ready",
        "category": "lifecycle",
        "details": {"component": "web"},
    },
)

# 主程序入口
if __name__ == '__main__':
    # 启动 Flask 应用
    #
    # Docker环境注意：
    # - host='0.0.0.0' 监听所有网络接口，允许容器外部访问
    # - host='127.0.0.1' 只允许容器内部访问，Docker端口映射会失效
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
