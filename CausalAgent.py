# app.py (Flask后端)
# Agent/MCP 长任务请通过 worker 进程运行。
from flask import Flask, jsonify, request, send_from_directory
import os
import logging
import json 
import sys
from flask import session
from app import create_app
try:
    from config.settings import settings
except (ValueError, FileNotFoundError) as e:
    logging.critical(f"无法加载应用配置，程序终止。错误: {e}")
    sys.exit(1)
# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 再次获取根logger并显式设置级别，以防被其他库覆盖
logging.getLogger().setLevel(logging.INFO)

app = create_app()

# 主程序入口
if __name__ == '__main__':
    logging.info("启动 Flask Web 层。Agent/MCP 长任务请通过 worker 进程运行。")
    # 启动 Flask 应用
    #
    # Docker环境注意：
    # - host='0.0.0.0' 监听所有网络接口，允许容器外部访问
    # - host='127.0.0.1' 只允许容器内部访问，Docker端口映射会失效
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
