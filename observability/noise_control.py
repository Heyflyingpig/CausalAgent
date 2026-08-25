"""高频后台故障的进程内降噪状态。"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading
import time
from typing import Hashable


@dataclass(frozen=True)
class FailureDecision:
    """一次失败是否应立即输出及其聚合计数。"""

    emit: bool
    failure_count: int
    suppressed_count: int


@dataclass(frozen=True)
class RecoveryDecision:
    """从失败状态恢复时提供的稳定统计。"""

    failure_count: int
    downtime_ms: int


@dataclass
class _FailureState:
    signature: str
    first_seen: float
    last_emitted: float
    failure_count: int = 1
    suppressed_count: int = 0


class FailureTransitionTracker:
    """记录首次、原因变化、定时提醒和一次恢复。"""

    def __init__(self, reminder_seconds: float = 300.0) -> None:
        if reminder_seconds <= 0:
            raise ValueError("reminder_seconds 必须大于 0")
        self.reminder_seconds = float(reminder_seconds)
        self._states: dict[Hashable, _FailureState] = {}
        self._lock = threading.RLock()

    def record_failure(
        self,
        key: Hashable,
        signature: str,
        *,
        now: float | None = None,
    ) -> FailureDecision:
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            state = self._states.get(key)
            if state is None:
                self._states[key] = _FailureState(signature, current, current)
                return FailureDecision(True, 1, 0)

            state.failure_count += 1
            changed = state.signature != signature
            reminder_due = current - state.last_emitted >= self.reminder_seconds
            if changed or reminder_due:
                suppressed = state.suppressed_count
                state.signature = signature
                state.last_emitted = current
                state.suppressed_count = 0
                return FailureDecision(True, state.failure_count, suppressed)

            state.suppressed_count += 1
            return FailureDecision(False, state.failure_count, state.suppressed_count)

    def record_success(
        self,
        key: Hashable,
        *,
        now: float | None = None,
    ) -> RecoveryDecision | None:
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            state = self._states.pop(key, None)
        if state is None:
            return None
        return RecoveryDecision(
            failure_count=state.failure_count,
            downtime_ms=max(0, int((current - state.first_seen) * 1000)),
        )

    def clear(self, key: Hashable) -> None:
        with self._lock:
            self._states.pop(key, None)


@dataclass
class _RepeatState:
    last_emitted: float
    suppressed_count: int = 0


class RepeatEventLimiter:
    """按键限制重复事件，并以 LRU 上限约束内存。"""

    def __init__(self, window_seconds: float = 300.0, max_keys: int = 1024) -> None:
        if window_seconds <= 0 or max_keys <= 0:
            raise ValueError("window_seconds 和 max_keys 必须大于 0")
        self.window_seconds = float(window_seconds)
        self.max_keys = int(max_keys)
        self._states: OrderedDict[Hashable, _RepeatState] = OrderedDict()
        self._lock = threading.RLock()

    def should_emit(
        self,
        key: Hashable,
        *,
        now: float | None = None,
    ) -> tuple[bool, int]:
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            state = self._states.get(key)
            if state is None:
                self._states[key] = _RepeatState(current)
                self._evict_locked()
                return True, 0

            self._states.move_to_end(key)
            if current - state.last_emitted >= self.window_seconds:
                suppressed = state.suppressed_count
                state.last_emitted = current
                state.suppressed_count = 0
                return True, suppressed

            state.suppressed_count += 1
            return False, state.suppressed_count

    def _evict_locked(self) -> None:
        while len(self._states) > self.max_keys:
            self._states.popitem(last=False)


__all__ = [
    "FailureDecision",
    "FailureTransitionTracker",
    "RecoveryDecision",
    "RepeatEventLimiter",
]
