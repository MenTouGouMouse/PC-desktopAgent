"""
集成测试：automation.software_installer 安装步骤序列集成。
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from automation.software_installer import INSTALL_STEPS, run_software_installer
from perception.element_locator import ElementResult


@pytest.mark.integration
class TestSoftwareInstallerIntegration:
    def test_complete_install_sequence_progress(self, tmp_path):
        """验证完整安装步骤序列的进度推送（4 步，percent 递增）。"""
        pkg = tmp_path / "installer.exe"
        pkg.write_bytes(b"fake")
        stop_event = threading.Event()
        percents: list[int] = []
        steps_called: list[str] = []

        def callback(step: str, percent: int) -> None:
            percents.append(percent)
            steps_called.append(step)

        mock_result = ElementResult(name="btn", bbox=(100, 100, 50, 30), confidence=0.9, strategy="test")

        with patch("subprocess.Popen"), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full", return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text", return_value=mock_result), \
             patch("execution.action_engine.ActionEngine.click"):
            run_software_installer(pkg, callback, stop_event)

        assert len(percents) == len(INSTALL_STEPS)
        assert percents == sorted(percents), "Percents should be monotonically increasing"
        assert percents[-1] == 100

    def test_stop_event_mid_execution_terminates_early(self, tmp_path):
        """验证 stop_event 中途设置时步骤提前终止。"""
        pkg = tmp_path / "installer.exe"
        pkg.write_bytes(b"fake")
        stop_event = threading.Event()
        call_count = 0

        def callback(step: str, percent: int) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                stop_event.set()

        mock_result = ElementResult(name="btn", bbox=(100, 100, 50, 30), confidence=0.9, strategy="test")

        with patch("subprocess.Popen"), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full", return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text", return_value=mock_result), \
             patch("execution.action_engine.ActionEngine.click"):
            run_software_installer(pkg, callback, stop_event)

        assert call_count <= 3, f"Expected at most 3 callbacks, got {call_count}"
        assert call_count < len(INSTALL_STEPS), "Should not have completed all steps"
