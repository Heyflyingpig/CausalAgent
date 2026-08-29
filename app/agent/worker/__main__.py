"""支持 ``python -m app.agent.worker`` 的模块入口。"""


if __name__ == "__main__":
    import logging

    from observability.logging_runtime import (
        configure_logging,
        current_environment,
        log_event,
    )

    configure_logging("worker", current_environment(), logging.INFO)
    logger = logging.getLogger(__name__)
    try:
        from app.agent.worker.bootstrap import main
    except Exception as exc:
        log_event(
            logger,
            "worker.startup.failed",
            details={
                "phase": "module_initialization",
                "dependency": "worker_runtime",
                "reason_code": "initialization_failed",
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        raise SystemExit(1) from None

    main()
