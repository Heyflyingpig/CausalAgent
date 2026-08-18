from flask import Flask
import logging

LOGGER = logging.getLogger(__name__)


def create_app():
    from config.settings import settings
    from app.db import check_database_readiness
    from app.auth.routes import auth_bp
    from app.chat.routes import chat_bp
    from app.files.routes import files_bp
    from app.agent.routes import agent_bp
    from app.main.routes import main_bp
    from app.admin.routes import admin_bp, admin_page_bp
    from app.request_context import register_request_context

    app = Flask(__name__, static_folder="static")
    app.secret_key = settings.SECRET_KEY
    register_request_context(app)

    try:
        check_database_readiness()
    except Exception:
        LOGGER.critical(
            "数据库检查失败，应用无法启动",
            extra={
                "event_code": "web.startup.failed",
                "category": "dependency",
                "details": {
                    "dependency": "mysql",
                    "reason_code": "readiness_failed",
                },
            },
            exc_info=True,
        )
        raise

    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(agent_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_page_bp)
    return app
