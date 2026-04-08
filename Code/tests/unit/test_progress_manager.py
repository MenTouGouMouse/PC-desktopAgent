"""
Unit tests for gui.progress_manager (TaskProgress + ProgressManager).

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gui.progress_manager import ProgressManager, TaskProgress


# ---------------------------------------------------------------------------
# TaskProgress dataclass
# ---------------------------------------------------------------------------


class TestTaskProgress:
    def test_default_values(self) -> None:
        tp = TaskProgress()
        assert tp.percent == 0
        assert tp.status_text == "就绪"
        assert tp.task_name == ""
        assert tp.is_running is False

    def test_custom_values(self) -> None:
        tp = TaskProgress(percent=50, status_text="运行中", task_name="file_organizer", is_running=True)
        assert tp.percent == 50
        assert tp.status_text == "运行中"
        assert tp.task_name == "file_organizer"
        assert tp.is_running is True


# ---------------------------------------------------------------------------
# ProgressManager.update — clamp behaviour
# ---------------------------------------------------------------------------


class TestProgressManagerUpdate:
    def test_update_normal_range(self) -> None:
        pm = ProgressManager()
        pm.update(50, "halfway")
        assert pm.get().percent == 50

    def test_update_clamps_above_100(self) -> None:
        pm = ProgressManager()
        pm.update(150, "over")
        assert pm.get().percent == 100

    def test_update_clamps_below_0(self) -> None:
        pm = ProgressManager()
        pm.update(-10, "under")
        assert pm.get().percent == 0

    def test_update_boundary_0(self) -> None:
        pm = ProgressManager()
        pm.update(0, "start")
        assert pm.get().percent == 0

    def test_update_boundary_100(self) -> None:
        pm = ProgressManager()
        pm.update(100, "done")
        assert pm.get().percent == 100

    def test_update_sets_all_fields(self) -> None:
        pm = ProgressManager()
        pm.update(42, "testing", task_name="my_task", is_running=True)
        state = pm.get()
        assert state.percent == 42
        assert state.status_text == "testing"
        assert state.task_name == "my_task"
        assert state.is_running is True

    def test_update_default_is_running_true(self) -> None:
        pm = ProgressManager()
        pm.update(10, "running")
        assert pm.get().is_running is True


# ---------------------------------------------------------------------------
# ProgressManager.reset
# ---------------------------------------------------------------------------


class TestProgressManagerReset:
    def test_reset_sets_defaults(self) -> None:
        pm = ProgressManager()
        pm.update(80, "busy", task_name="task", is_running=True)
        pm.reset()
        state = pm.get()
        assert state.percent == 0
        assert state.is_running is False
        assert state.status_text == "就绪"

    def test_reset_notifies_subscribers(self) -> None:
        pm = ProgressManager()
        cb = MagicMock()
        pm.subscribe(cb)
        pm.reset()
        cb.assert_called_once()
        called_with: TaskProgress = cb.call_args[0][0]
        assert called_with.percent == 0
        assert called_with.is_running is False


# ---------------------------------------------------------------------------
# ProgressManager.get — returns copy
# ---------------------------------------------------------------------------


class TestProgressManagerGet:
    def test_get_returns_copy(self) -> None:
        pm = ProgressManager()
        pm.update(30, "mid")
        a = pm.get()
        b = pm.get()
        assert a is not b
        assert a.percent == b.percent

    def test_mutating_copy_does_not_affect_state(self) -> None:
        pm = ProgressManager()
        pm.update(30, "mid")
        copy = pm.get()
        copy.percent = 99
        assert pm.get().percent == 30


# ---------------------------------------------------------------------------
# ProgressManager.subscribe / unsubscribe
# ---------------------------------------------------------------------------


class TestProgressManagerSubscribers:
    def test_subscribe_callback_called_on_update(self) -> None:
        pm = ProgressManager()
        cb = MagicMock()
        pm.subscribe(cb)
        pm.update(10, "step")
        cb.assert_called_once()

    def test_subscribe_callback_receives_updated_progress(self) -> None:
        pm = ProgressManager()
        received: list[TaskProgress] = []
        pm.subscribe(received.append)
        pm.update(55, "halfway", task_name="t", is_running=True)
        assert len(received) == 1
        assert received[0].percent == 55
        assert received[0].status_text == "halfway"

    def test_multiple_subscribers_all_notified(self) -> None:
        pm = ProgressManager()
        cb1, cb2, cb3 = MagicMock(), MagicMock(), MagicMock()
        pm.subscribe(cb1)
        pm.subscribe(cb2)
        pm.subscribe(cb3)
        pm.update(20, "x")
        cb1.assert_called_once()
        cb2.assert_called_once()
        cb3.assert_called_once()

    def test_unsubscribe_stops_notification(self) -> None:
        pm = ProgressManager()
        cb = MagicMock()
        pm.subscribe(cb)
        pm.unsubscribe(cb)
        pm.update(10, "step")
        cb.assert_not_called()

    def test_unsubscribe_unknown_callback_does_not_raise(self) -> None:
        pm = ProgressManager()
        cb = MagicMock()
        pm.unsubscribe(cb)  # should not raise

    def test_duplicate_subscribe_registers_once(self) -> None:
        pm = ProgressManager()
        cb = MagicMock()
        pm.subscribe(cb)
        pm.subscribe(cb)
        pm.update(10, "step")
        cb.assert_called_once()

    def test_subscriber_exception_does_not_prevent_others(self) -> None:
        pm = ProgressManager()
        bad_cb = MagicMock(side_effect=RuntimeError("boom"))
        good_cb = MagicMock()
        pm.subscribe(bad_cb)
        pm.subscribe(good_cb)
        pm.update(10, "step")  # should not raise
        good_cb.assert_called_once()


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestProgressManagerThreadSafety:
    def test_concurrent_updates_do_not_corrupt_state(self) -> None:
        pm = ProgressManager()
        errors: list[Exception] = []

        def worker(value: int) -> None:
            try:
                pm.update(value, f"status-{value}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i % 101,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        state = pm.get()
        assert 0 <= state.percent <= 100

    def test_concurrent_subscribe_unsubscribe_safe(self) -> None:
        pm = ProgressManager()
        callbacks = [MagicMock() for _ in range(10)]
        errors: list[Exception] = []

        def sub_unsub(cb: MagicMock) -> None:
            try:
                pm.subscribe(cb)
                pm.update(50, "mid")
                pm.unsubscribe(cb)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=sub_unsub, args=(cb,)) for cb in callbacks]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------


class TestProgressManagerProperties:
    @given(percent=st.integers())
    @settings(max_examples=200)
    def test_percent_always_clamped(self, percent: int) -> None:
        """**Validates: Requirements 2.2**

        For any integer percent, get().percent is always in [0, 100].
        """
        pm = ProgressManager()
        pm.update(percent, "text")
        result = pm.get().percent
        assert 0 <= result <= 100

    @given(n=st.integers(min_value=1, max_value=20))
    @settings(max_examples=50)
    def test_all_n_subscribers_notified_exactly_once(self, n: int) -> None:
        """**Validates: Requirements 2.3**

        N registered callbacks are each called exactly once per update().
        """
        pm = ProgressManager()
        callbacks = [MagicMock() for _ in range(n)]
        for cb in callbacks:
            pm.subscribe(cb)
        pm.update(50, "test")
        for cb in callbacks:
            cb.assert_called_once()

    @given(percent=st.integers(min_value=0, max_value=100), status=st.text(min_size=1, max_size=50))
    @settings(max_examples=100)
    def test_unsubscribed_callback_never_called(self, percent: int, status: str) -> None:
        """**Validates: Requirements 2.7**

        After unsubscribe(), the callback is never invoked on subsequent updates.
        """
        pm = ProgressManager()
        cb = MagicMock()
        pm.subscribe(cb)
        pm.unsubscribe(cb)
        pm.update(percent, status)
        cb.assert_not_called()
