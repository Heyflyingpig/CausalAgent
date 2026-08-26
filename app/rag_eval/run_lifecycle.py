"""评测运行状态、结果、产物和取消操作的统一适配层。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunArtifact:
    """描述运行产物的文件位置及响应媒体类型。"""

    path: Path
    media_type: str


class RunLifecycle:
    """为评测运行管理器提供统一的状态、结果、产物和取消操作。"""

    def __init__(self, manager) -> None:
        self._manager = manager

    def get_state(self, run_id: str) -> dict[str, Any]:
        """读取指定运行的当前状态。"""
        return self._manager.get(run_id)

    def get_result(self, run_id: str) -> dict[str, Any]:
        """读取指定运行的最终结果。"""
        return self._manager.get_result(run_id)

    def get_artifact(self, run_id: str, artifact_name: str) -> RunArtifact:
        """解析运行产物路径，并根据扩展名确定响应媒体类型。"""
        path = self._manager.get_artifact_path(run_id, artifact_name)
        media_type = (
            "application/json"
            if path.suffix.lower() == ".json"
            else "text/markdown; charset=utf-8"
            if path.suffix.lower() in {".md", ".markdown"}
            else "text/plain; charset=utf-8"
        )
        return RunArtifact(path=path, media_type=media_type)

    def cancel(self, run_id: str) -> dict[str, Any]:
        """向底层运行管理器转发取消请求。"""
        return self._manager.cancel(run_id)
