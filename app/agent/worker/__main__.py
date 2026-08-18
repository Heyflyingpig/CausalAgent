"""支持 ``python -m app.agent.worker`` 的模块入口。"""


if __name__ == "__main__":
    import logging

    from observability.logging_runtime import configure_logging, current_environment

    configure_logging("worker", current_environment(), logging.INFO)
    from app.agent.worker.bootstrap import main

    main()
