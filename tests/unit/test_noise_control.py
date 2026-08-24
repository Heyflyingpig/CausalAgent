"""高频后台故障转换和限频状态测试。"""

from __future__ import annotations

from observability.noise_control import FailureTransitionTracker, RepeatEventLimiter


def test_failure_tracker_emits_first_change_reminder_and_single_recovery():
    tracker = FailureTransitionTracker(reminder_seconds=300)

    first = tracker.record_failure("replica", "network", now=10)
    repeated = tracker.record_failure("replica", "network", now=20)
    changed = tracker.record_failure("replica", "lag", now=30)
    suppressed = tracker.record_failure("replica", "lag", now=40)
    reminder = tracker.record_failure("replica", "lag", now=331)
    recovery = tracker.record_success("replica", now=350)

    assert (first.emit, first.failure_count, first.suppressed_count) == (True, 1, 0)
    assert (repeated.emit, repeated.failure_count) == (False, 2)
    assert (changed.emit, changed.failure_count, changed.suppressed_count) == (True, 3, 1)
    assert suppressed.emit is False
    assert (reminder.emit, reminder.failure_count, reminder.suppressed_count) == (True, 5, 1)
    assert recovery is not None
    assert recovery.failure_count == 5
    assert recovery.downtime_ms == 340_000
    assert tracker.record_success("replica", now=351) is None


def test_repeat_limiter_reports_suppressed_count_and_evicts_lru_keys():
    limiter = RepeatEventLimiter(window_seconds=300, max_keys=2)

    assert limiter.should_emit("a", now=0) == (True, 0)
    assert limiter.should_emit("a", now=1) == (False, 1)
    assert limiter.should_emit("b", now=2) == (True, 0)
    assert limiter.should_emit("a", now=301) == (True, 1)
    assert limiter.should_emit("c", now=302) == (True, 0)
    # b 是最久未访问的键，已被逐出；再次出现按首次处理。
    assert limiter.should_emit("b", now=303) == (True, 0)
