"""验证固定 causal-learn 版本在 Python 3.11 中可执行 DirectLiNGAM。"""

from __future__ import annotations

from importlib.metadata import version

import networkx as nx
import numpy as np
from causallearn.search.FCMBased import lingam


EXPECTED_CAUSAL_LEARN_VERSION = "0.1.4.7"
EXPECTED_LINGAM_VERSION = "1.5.4"


def build_six_variable_sem(sample_count: int = 1000) -> np.ndarray:
    """生成 causal-learn 上游测试使用的六变量非高斯线性 SEM。"""
    random = np.random.RandomState(100)
    x3 = random.uniform(size=sample_count)
    x0 = 3.0 * x3 + random.uniform(size=sample_count)
    x2 = 6.0 * x3 + random.uniform(size=sample_count)
    x1 = 3.0 * x0 + 2.0 * x2 + random.uniform(size=sample_count)
    x5 = 4.0 * x0 + random.uniform(size=sample_count)
    x4 = 8.0 * x0 - 1.0 * x2 + random.uniform(size=sample_count)
    return np.column_stack([x0, x1, x2, x3, x4, x5])


def run_smoke() -> None:
    """执行版本、拟合结果、矩阵方向和 DAG 基本性质检查。"""
    assert version("causal-learn") == EXPECTED_CAUSAL_LEARN_VERSION
    assert lingam.__version__ == EXPECTED_LINGAM_VERSION

    data = build_six_variable_sem()
    model = lingam.DirectLiNGAM(measure="pwling")
    model.fit(data)

    causal_order = [int(index) for index in model.causal_order_]
    adjacency_matrix = np.asarray(model.adjacency_matrix_, dtype=float)

    assert sorted(causal_order) == list(range(data.shape[1]))
    assert adjacency_matrix.shape == (data.shape[1], data.shape[1])
    assert np.isfinite(adjacency_matrix).all()
    assert np.allclose(np.diag(adjacency_matrix), 0.0)

    # DirectLiNGAM 使用 B[target, source]；networkx 使用 A[source, target]。
    source_to_target = (adjacency_matrix.T != 0).astype(int)
    graph = nx.from_numpy_array(source_to_target, create_using=nx.DiGraph)
    assert nx.is_directed_acyclic_graph(graph)

    expected_edges = {
        (3, 0),
        (3, 2),
        (0, 1),
        (2, 1),
        (0, 5),
        (0, 4),
        (2, 4),
    }
    assert set(graph.edges()) == expected_edges

    print(
        "DirectLiNGAM smoke passed: "
        f"causal-learn={version('causal-learn')}, "
        f"lingam={lingam.__version__}, "
        f"causal_order={causal_order}, "
        f"edge_count={graph.number_of_edges()}"
    )


if __name__ == "__main__":
    run_smoke()
