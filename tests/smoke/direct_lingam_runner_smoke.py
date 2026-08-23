"""在锁定的 Python 3.11 环境中验证项目 DirectLiNGAM runner。"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Agent.causal.causalachieve import run_direct_lingam_analysis
from direct_lingam_smoke import build_six_variable_sem


def run_runner_smoke() -> None:
    """执行真实拟合，并核对 runner 成功契约的关键行为。"""
    node_names = ["x0", "x1", "x2", "x3", "x4", "x5"]
    data = build_six_variable_sem()
    csv_data = pd.DataFrame(data, columns=node_names).to_csv(index=False)

    result = run_direct_lingam_analysis(csv_data)

    assert result["success"] is True, result
    assert result["implementation"]["version"] == "0.1.4.7"
    assert result["implementation"]["embedded_version"] == "1.5.4"
    assert result["parameters"] == {"measure": "pwling"}
    assert result["matrix_convention"] == "target_to_source"

    causal_order = result["raw_results"]["causal_order"]
    adjacency_matrix = np.asarray(
        result["raw_results"]["adjacency_matrix"],
        dtype=float,
    )
    assert sorted(causal_order) == list(range(len(node_names)))
    assert result["raw_results"]["causal_order_names"] == [
        node_names[index] for index in causal_order
    ]
    assert adjacency_matrix.shape == (len(node_names), len(node_names))

    expected_edges = {
        ("x3", "x0"),
        ("x3", "x2"),
        ("x0", "x1"),
        ("x2", "x1"),
        ("x0", "x5"),
        ("x0", "x4"),
        ("x2", "x4"),
    }
    actual_edges = {
        (edge["from"], edge["to"])
        for edge in result["data"]["edges"]
    }
    assert actual_edges == expected_edges

    node_index = {name: index for index, name in enumerate(node_names)}
    for edge in result["data"]["edges"]:
        source_index = node_index[edge["from"]]
        target_index = node_index[edge["to"]]
        assert edge["weight"] == adjacency_matrix[target_index, source_index]

    print(
        "DirectLiNGAM runner smoke passed: "
        f"causal_order={causal_order}, edge_count={len(actual_edges)}"
    )


if __name__ == "__main__":
    run_runner_smoke()
