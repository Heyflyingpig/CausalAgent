"""PC、OLC、DirectLiNGAM 的应用侧 Adapter。"""

from .base import AdapterInput, AlgorithmAdapter, BaseAlgorithmAdapter
from .direct_lingam import DirectLiNGAMAdapter
from .olc import OlcAdapter
from .pc import PcAdapter


def build_default_adapters(*, executor, raw_backend=None) -> dict[str, BaseAlgorithmAdapter]:
    """构造首版三项静态 Adapter 绑定，不读取远端动态工具清单。"""

    return {
        "causal.pc": PcAdapter(executor=executor, raw_backend=raw_backend),
        "causal.olc": OlcAdapter(executor=executor, raw_backend=raw_backend),
        "causal.direct_lingam": DirectLiNGAMAdapter(
            executor=executor,
            raw_backend=raw_backend,
        ),
    }

__all__ = [
    "AdapterInput",
    "AlgorithmAdapter",
    "BaseAlgorithmAdapter",
    "build_default_adapters",
    "DirectLiNGAMAdapter",
    "OlcAdapter",
    "PcAdapter",
]
