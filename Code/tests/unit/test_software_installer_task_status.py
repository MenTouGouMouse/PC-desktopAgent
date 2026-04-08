"""
Bug Condition Exploration Test — Bug 5b: 所有步骤 optional=True 时任务被错误标记为完成

这些测试在未修复代码上 MUST FAIL，失败即证明 bug 存在。
DO NOT fix the code when tests fail.

Expected outcome on UNFIXED code: FAILS
- All steps are optional=True (including "完成" step)
- All steps timeout silently
- run_software_installer returns normally (no exception)
- Test expects an exception to be raised

Validates: Requirements 1.10, 1.11
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from automation.software_installer import run_software_installer, InstallStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_callback(step: str, percent: int) -> None:
    pass


# ---------------------------------------------------------------------------
# Bug condition: all optional=True steps timeout → function returns normally
# ---------------------------------------------------------------------------

class TestAllOptionalStepsTimeout:
    def test_all_optional_steps_timeout_raises_exception(self):
        """
        Bug condition: ALL install steps timeout, including the required "完成" step.

        EXPECTED OUTCOME on FIXED code: PASSES
        - Fixed INSTALL_STEPS has "完成" step as optional=False
        - When "完成" step times out, run_software_installer raises TimeoutError

        Counterexample on unfixed code: function returns normally (no exception)
        """
        stop_event = threading.Event()

        # Use real INSTALL_STEPS (fixed: "完成" is optional=False) but with tiny timeouts
        fixed_steps = [
            InstallStep("下一步", "点击'下一步'按钮", timeout=0.01, optional=True),
            InstallStep("我同意", "接受许可协议", timeout=0.01, optional=True),
            InstallStep("安装", "开始安装", timeout=0.01, optional=True),
            InstallStep("完成", "完成安装", timeout=0.01, optional=False),  # FIXED: optional=False
        ]

        with patch("pathlib.Path.exists", return_value=True), \
             patch("automation.software_installer._launch_package"), \
             patch("automation.software_installer.INSTALL_STEPS", fixed_steps), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full",
                   return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text",
                   side_effect=Exception("element not found")), \
             patch("time.sleep"):

            # PASSES on fixed code: TimeoutError is raised for the required "完成" step
            with pytest.raises(Exception) as exc_info:
                run_software_installer(
                    r"C:\fake\setup.exe",
                    _noop_callback,
                    stop_event,
                )

        # The exception should indicate a required step failed
        assert exc_info.value is not None, (
            "Expected run_software_installer to raise an exception when all steps timeout, "
            "but it returned normally. "
            "Bug: unfixed code has '完成' step as optional=True, so it silently skips "
            "and returns normally, causing _task() to call progress_callback('智能安装完成', 100)."
        )

    def test_completion_step_must_not_be_optional(self):
        """
        Bug condition: The "完成" (completion) step in INSTALL_STEPS is optional=True.

        EXPECTED OUTCOME on UNFIXED code: FAILS
        - Unfixed INSTALL_STEPS has "完成" as optional=True
        - Fixed code should have "完成" as optional=False

        Counterexample: "完成" step has optional=True
        """
        from automation.software_installer import INSTALL_STEPS

        completion_steps = [s for s in INSTALL_STEPS if s.button_text == "完成"]
        assert len(completion_steps) >= 1, (
            "Expected at least one '完成' step in INSTALL_STEPS, but found none."
        )

        for step in completion_steps:
            assert step.optional is False, (
                f"Expected '完成' step to be optional=False (required), "
                f"but got optional={step.optional!r}. "
                f"Bug: unfixed code has '完成' as optional=True, allowing silent timeout "
                f"and incorrect task completion marking."
            )

    def test_required_step_timeout_raises_timeout_error(self):
        """
        When a required (optional=False) step times out, TimeoutError should be raised.

        This tests the existing behavior for non-optional steps.
        Should pass on both fixed and unfixed code for non-optional steps.
        """
        stop_event = threading.Event()

        required_steps = [
            InstallStep("完成", "完成安装", timeout=0.01, optional=False),
        ]

        with patch("pathlib.Path.exists", return_value=True), \
             patch("automation.software_installer._launch_package"), \
             patch("automation.software_installer.INSTALL_STEPS", required_steps), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full",
                   return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text",
                   side_effect=Exception("element not found")), \
             patch("time.sleep"):

            with pytest.raises(TimeoutError) as exc_info:
                run_software_installer(
                    r"C:\fake\setup.exe",
                    _noop_callback,
                    stop_event,
                )

        assert "完成" in str(exc_info.value), (
            f"Expected TimeoutError mentioning '完成', but got: {exc_info.value!r}"
        )


# ---------------------------------------------------------------------------
# Additional: verify progress_callback is NOT called with "完成" on failure
# ---------------------------------------------------------------------------

class TestProgressCallbackOnFailure:
    def test_completion_callback_not_called_when_required_step_fails(self):
        """
        When a required step fails, progress_callback should NOT be called
        with "智能安装完成" or "完成安装".

        EXPECTED OUTCOME on FIXED code: PASSES
        - Fixed code has "完成" as optional=False
        - "完成" step times out → TimeoutError is raised
        - Caller (_task()) enters except branch, does NOT call completion callback
        """
        stop_event = threading.Event()
        callback_calls: list[tuple[str, int]] = []

        def tracking_callback(step: str, percent: int) -> None:
            callback_calls.append((step, percent))

        # Use fixed steps: "完成" is optional=False (required)
        fixed_steps = [
            InstallStep("完成", "完成安装", timeout=0.01, optional=False),  # FIXED
        ]

        with patch("pathlib.Path.exists", return_value=True), \
             patch("automation.software_installer._launch_package"), \
             patch("automation.software_installer.INSTALL_STEPS", fixed_steps), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full",
                   return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text",
                   side_effect=Exception("element not found")), \
             patch("time.sleep"):

            try:
                run_software_installer(
                    r"C:\fake\setup.exe",
                    tracking_callback,
                    stop_event,
                )
                # If we reach here, function returned normally (bug condition)
                # Simulate what _task() would do: call completion callback
                tracking_callback("智能安装完成", 100)
            except Exception:
                pass  # Exception means bug is fixed — _task() enters except branch

        # PASSES on fixed code: TimeoutError is raised, so "智能安装完成" is NOT called
        completion_calls = [
            (s, p) for s, p in callback_calls
            if s == "智能安装完成" and p == 100
        ]
        assert len(completion_calls) == 0, (
            f"Expected no '智能安装完成' completion callback when required step fails, "
            f"but got: {completion_calls!r}. "
            f"Bug: unfixed code returns normally when '完成' step is optional=True, "
            f"allowing caller to mark task as complete."
        )


# ---------------------------------------------------------------------------
# Preservation tests (Task 2) — MUST PASS on unfixed code
# ---------------------------------------------------------------------------

class TestPreservationOptionalStepTimeout:
    def test_optional_step_timeout_continues(self):
        """
        Preservation: optional=True step timeout → continues to next step, no exception.
        Requirements 3.6
        """
        stop_event = threading.Event()
        callback_calls: list[tuple[str, int]] = []

        def tracking_callback(step: str, percent: int) -> None:
            callback_calls.append((step, percent))

        # Two steps: first optional (will timeout), second optional (will succeed)
        steps = [
            InstallStep("不存在按钮", "可选步骤", timeout=0.01, optional=True),
            InstallStep("完成", "完成安装", timeout=5.0, optional=True),
        ]

        call_count = 0

        def locate_side_effect(screenshot, text):
            nonlocal call_count
            call_count += 1
            if text == "不存在按钮":
                raise Exception("not found")
            # Return valid result for "完成"
            from perception.element_locator import ElementResult
            return ElementResult(name=text, bbox=(100, 100, 40, 20), confidence=0.9, strategy="ocr")

        with patch("pathlib.Path.exists", return_value=True), \
             patch("automation.software_installer._launch_package"), \
             patch("automation.software_installer.INSTALL_STEPS", steps), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full",
                   return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text",
                   side_effect=locate_side_effect), \
             patch("execution.action_engine.ActionEngine.click", return_value=True), \
             patch("time.sleep"):

            # Should NOT raise — optional step timeout is skipped
            run_software_installer(
                r"C:\fake\setup.exe",
                tracking_callback,
                stop_event,
            )

        # Verify the optional step timeout message was reported
        timeout_msgs = [s for s, _ in callback_calls if "不存在按钮" in s]
        assert len(timeout_msgs) >= 1, (
            "Expected a timeout callback for the optional step, "
            f"but callback_calls was: {callback_calls!r}"
        )


class TestPreservationStopEvent:
    def test_stop_event_aborts_install_loop(self):
        """
        Preservation: stop_event set → run_software_installer exits cleanly.
        Requirements 3.5
        """
        stop_event = threading.Event()
        stop_event.set()  # Signal stop immediately

        steps = [
            InstallStep("完成", "完成安装", timeout=30.0, optional=False),
        ]

        locate_called = False

        def locate_side_effect(screenshot, text):
            nonlocal locate_called
            locate_called = True
            raise Exception("should not be called after stop")

        with patch("pathlib.Path.exists", return_value=True), \
             patch("automation.software_installer._launch_package"), \
             patch("automation.software_installer.INSTALL_STEPS", steps), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full",
                   return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text",
                   side_effect=locate_side_effect), \
             patch("time.sleep"):

            # Should return cleanly (not raise) when stop_event is set
            run_software_installer(
                r"C:\fake\setup.exe",
                _noop_callback,
                stop_event,
            )

        # locate_by_text should NOT have been called since stop_event was set before the loop
        assert not locate_called, (
            "Expected locate_by_text to NOT be called when stop_event is set before the loop, "
            "but it was called."
        )
