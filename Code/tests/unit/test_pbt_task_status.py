"""
Preservation Property Test — 所有非可选步骤成功时 run_software_installer 正常返回

这些测试在未修复代码上 MUST PASS — 记录基线行为，修复后必须保持。

Validates: Requirements 3.6
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from automation.software_installer import run_software_installer, InstallStep
from perception.element_locator import ElementResult


def _noop_callback(step: str, percent: int) -> None:
    pass


def _make_element_result(x: int = 100, y: int = 100) -> ElementResult:
    return ElementResult(
        name="button",
        bbox=(x - 20, y - 10, 40, 20),
        confidence=0.95,
        strategy="ocr",
    )


class TestTaskStatusPreservationProperty:
    """Property: when all non-optional steps succeed, run_software_installer returns normally."""

    def test_all_steps_succeed_returns_normally(self) -> None:
        """
        **Validates: Requirements 3.6**

        Baseline: when locate_by_text returns valid ElementResult for every step,
        run_software_installer completes without raising an exception.
        """
        stop_event = threading.Event()

        success_steps = [
            InstallStep("下一步", "点击'下一步'按钮", timeout=5.0, optional=True),
            InstallStep("我同意", "接受许可协议", timeout=5.0, optional=True),
            InstallStep("安装", "开始安装", timeout=5.0, optional=True),
            InstallStep("完成", "完成安装", timeout=5.0, optional=True),
        ]

        with patch("pathlib.Path.exists", return_value=True), \
             patch("automation.software_installer._launch_package"), \
             patch("automation.software_installer.INSTALL_STEPS", success_steps), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full",
                   return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text",
                   return_value=_make_element_result()), \
             patch("execution.action_engine.ActionEngine.click", return_value=True), \
             patch("time.sleep"):

            # Should NOT raise
            run_software_installer(
                r"C:\fake\setup.exe",
                _noop_callback,
                stop_event,
            )

    @given(st.integers(min_value=1, max_value=5))
    @settings(max_examples=20)
    def test_n_optional_steps_all_succeed_returns_normally(self, n: int) -> None:
        """
        **Validates: Requirements 3.6**

        Property: for any number of optional steps (1-5) that all succeed,
        run_software_installer returns normally without exception.
        """
        stop_event = threading.Event()

        steps = [
            InstallStep(f"步骤{i}", f"执行步骤{i}", timeout=5.0, optional=True)
            for i in range(n)
        ]

        with patch("pathlib.Path.exists", return_value=True), \
             patch("automation.software_installer._launch_package"), \
             patch("automation.software_installer.INSTALL_STEPS", steps), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full",
                   return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text",
                   return_value=_make_element_result()), \
             patch("execution.action_engine.ActionEngine.click", return_value=True), \
             patch("time.sleep"):

            # Should NOT raise for any n
            try:
                run_software_installer(
                    r"C:\fake\setup.exe",
                    _noop_callback,
                    stop_event,
                )
            except Exception as exc:
                pytest.fail(
                    f"Expected run_software_installer to return normally when all {n} steps succeed, "
                    f"but raised: {exc!r}"
                )
