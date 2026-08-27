"""RAG评测管理蓝图 —— 面向开发者的调参与pipeline触发接口。"""

from flask import Blueprint

rag_eval_bp = Blueprint("rag_eval", __name__, url_prefix="/api/rag_eval")

from app.rag_eval.routes import *  # noqa: E402, F403
