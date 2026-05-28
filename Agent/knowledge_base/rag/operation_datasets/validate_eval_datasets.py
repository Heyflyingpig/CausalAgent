import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[4]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from Agent.knowledge_base.rag.operation_datasets.dataset_utils import (
    validate_all_datasets,
    write_dataset_validation_outputs,
)


def validate_all() -> dict:
    """校验所有 RAG eval 数据集；保留旧函数名作为入口兼容。"""
    return validate_all_datasets()


if __name__ == "__main__":
    validation_result = validate_all()
    write_dataset_validation_outputs(validation_result)
    print(json.dumps(validation_result, ensure_ascii=False, indent=2))
    sys.exit(0 if validation_result["status"] == "pass" else 1)

