"""P2-U 内存 Store、权限和 raw result 协议测试。"""

import pytest

from Agent.deep_agent.memory import (
    MEMORY_PATHS,
    MemoryPermissionError,
    build_in_memory_backend,
    initialize_memory_files,
    trusted_memory_namespace,
)


def test_memory_files_are_create_if_absent_and_namespace_isolated() -> None:
    store: dict = {}
    first = build_in_memory_backend(user_id=7, store=store)
    assert set(initialize_memory_files(first)) == set()
    first.model_edit_file(MEMORY_PATHS[0], "language=zh")

    second_job = build_in_memory_backend(user_id=7, store=store)
    assert second_job.model_read_file(MEMORY_PATHS[0]) == "language=zh"
    other_user = build_in_memory_backend(user_id=8, store=store)
    assert other_user.model_read_file(MEMORY_PATHS[0]) != "language=zh"


def test_model_cannot_write_other_virtual_paths_but_trusted_adapter_can() -> None:
    backend = build_in_memory_backend(user_id=7)
    with pytest.raises(MemoryPermissionError):
        backend.model_edit_file("/raw_algorithm_results/inv/0.json", "raw")
    metadata = backend.write_raw_result(
        raw_result_ref="/raw_algorithm_results/inv/0.json",
        raw_result={"z": 1, "a": "中文"},
    )
    assert backend.read(metadata.raw_result_ref) is not None
    assert metadata.raw_result_size_bytes > 0


def test_namespace_comes_from_trusted_identity_not_model_arguments() -> None:
    class Runtime:
        class Identity:
            user_id = 42

        trusted_identity = Identity()

    assert trusted_memory_namespace(Runtime()) == ("causalagent", "memory", "42")

