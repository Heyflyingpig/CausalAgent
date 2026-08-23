"""支持 ``python -m app.agent.worker`` 的模块入口。"""

from app.agent.worker.bootstrap import main


if __name__ == "__main__":
    main()
