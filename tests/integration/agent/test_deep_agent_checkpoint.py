"""P2-U 隔离 Store/checkpoint 边界的协议测试（不连接真实 PostgreSQL）。"""

import asyncio

from Agent.deep_agent.memory import build_in_memory_backend
from Agent.deep_agent.postgres_store import (
    PostgresStoreConfig,
    filter_checkpoint_cleanup_tables,
    open_async_postgres_store,
)


def test_store_survives_new_backend_instance_and_cleanup_excludes_store_tables() -> None:
    store = {}
    backend = build_in_memory_backend(user_id=11, store=store)
    backend.model_edit_file("/memories/preferences.md", "stable")
    restored = build_in_memory_backend(user_id=11, store=store)
    assert restored.model_read_file("/memories/preferences.md") == "stable"
    assert filter_checkpoint_cleanup_tables(["checkpoints", "checkpoint_writes", "store", "store_migrations"]) == (
        "checkpoints",
        "checkpoint_writes",
    )


def test_official_store_factory_owns_context_and_runs_setup(monkeypatch) -> None:
    import langgraph.store.postgres as postgres_module

    events = []

    class Store:
        async def setup(self):
            events.append("setup")

    class Context:
        async def __aenter__(self):
            events.append("enter")
            return Store()

        async def __aexit__(self, exc_type, exc, traceback):
            events.append("exit")

    class FakeAsyncPostgresStore:
        @classmethod
        def from_conn_string(cls, conn_string):
            assert conn_string == "safe-conninfo"
            return Context()

    monkeypatch.setattr(postgres_module, "AsyncPostgresStore", FakeAsyncPostgresStore)
    monkeypatch.setattr(
        PostgresStoreConfig,
        "connection_string",
        lambda self: "safe-conninfo",
    )
    config = PostgresStoreConfig(
        host="postgres",
        port=5432,
        database="db",
        user="user",
        password="secret",
        connect_timeout_seconds=5,
        pool_min_size=1,
        pool_max_size=2,
    )

    async def scenario():
        async with open_async_postgres_store(config=config) as store:
            assert isinstance(store, Store)
            events.append("yield")

    asyncio.run(scenario())
    assert events == ["enter", "setup", "yield", "exit"]
