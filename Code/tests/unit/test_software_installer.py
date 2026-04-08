"""
单元测试：automation.software_installer 真实实现。
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from automation.software_installer import INSTALL_STEPS, InstallStep, run_software_installer
from perception.element_locator import ElementResult


class TestRunSoftwareInstallerErrors:
    def test_package_path_not_exist_raises_file_not_found(self, tmp_path):
        """package_path 不存在时抛出 FileNotFoundError，不调用 subprocess.Popen。"""
        pkg = tmp_path / "nonexistent.exe"
        stop_event = threading.Event()
        callbacks = []

        with patch("subprocess.Popen") as mock_popen:
            with pytest.raises(FileNotFoundError) as exc_info:
                run_software_installer(pkg, lambda s, p: callbacks.append(p), stop_event)

            mock_popen.assert_not_called()

        assert str(pkg) in str(exc_info.value)
        assert len(callbacks) == 0

    def test_button_locate_timeout_raises_timeout_error(self, tmp_path):
        """按钮定位超时时抛出 TimeoutError 并调用 callback 上报超时信息。"""
        pkg = tmp_path / "installer.exe"
        pkg.write_bytes(b"fake")
        stop_event = threading.Event()
        callbacks: list[tuple[str, int]] = []

        # Use a very short timeout step
        short_step = InstallStep("不存在的按钮", "测试步骤", timeout=0.1)

        with patch("subprocess.Popen"), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full", return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text", side_effect=Exception("not found")), \
             patch("execution.action_engine.ActionEngine.click"), \
             patch("automation.software_installer.INSTALL_STEPS", [short_step]):
            with pytest.raises(TimeoutError):
                run_software_installer(pkg, lambda s, p: callbacks.append((s, p)), stop_event)

        # Callback should have been called with timeout message
        assert len(callbacks) >= 1
        timeout_msgs = [s for s, p in callbacks if "超时" in s]
        assert len(timeout_msgs) >= 1

    def test_subprocess_popen_called_with_package_path(self, tmp_path):
        """subprocess.Popen 被正确调用（路径参数）。"""
        pkg = tmp_path / "installer.exe"
        pkg.write_bytes(b"fake")
        stop_event = threading.Event()

        mock_result = ElementResult(name="btn", bbox=(100, 100, 50, 30), confidence=0.9, strategy="test")

        with patch("subprocess.Popen") as mock_popen, \
             patch("perception.screen_capturer.ScreenCapturer.capture_full", return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text", return_value=mock_result), \
             patch("execution.action_engine.ActionEngine.click"):
            run_software_installer(pkg, lambda s, p: None, stop_event)

        mock_popen.assert_called_once_with([str(pkg)])


class TestRunSoftwareInstallerStopEvent:
    def test_stop_event_set_before_first_step_returns_immediately(self, tmp_path):
        """stop_event 在第一步前已设置时立即返回，不执行任何步骤。"""
        pkg = tmp_path / "installer.exe"
        pkg.write_bytes(b"fake")
        stop_event = threading.Event()
        stop_event.set()  # Set before calling
        callbacks: list[tuple[str, int]] = []

        with patch("subprocess.Popen"), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full") as mock_capture, \
             patch("perception.element_locator.ElementLocator.locate_by_text") as mock_locate, \
             patch("execution.action_engine.ActionEngine.click") as mock_click:
            run_software_installer(pkg, lambda s, p: callbacks.append((s, p)), stop_event)

        # No steps should have been executed
        assert len(callbacks) == 0
        mock_locate.assert_not_called()
        mock_click.assert_not_called()

    def test_stop_event_mid_execution_halts_steps(self, tmp_path):
        """stop_event 在执行中途设置时停止后续步骤。"""
        pkg = tmp_path / "installer.exe"
        pkg.write_bytes(b"fake")
        stop_event = threading.Event()
        callbacks: list[tuple[str, int]] = []
        call_count = 0

        def callback(step: str, percent: int) -> None:
            nonlocal call_count
            call_count += 1
            callbacks.append((step, percent))
            if call_count >= 2:
                stop_event.set()

        mock_result = ElementResult(name="btn", bbox=(100, 100, 50, 30), confidence=0.9, strategy="test")

        with patch("subprocess.Popen"), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full", return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text", return_value=mock_result), \
             patch("execution.action_engine.ActionEngine.click"):
            run_software_installer(pkg, callback, stop_event)

        # Should have stopped after 2 callbacks
        assert call_count <= 3


class TestRunSoftwareInstallerProgress:
    def test_progress_percent_increases_per_step(self, tmp_path):
        """每步完成后进度百分比递增。"""
        pkg = tmp_path / "installer.exe"
        pkg.write_bytes(b"fake")
        stop_event = threading.Event()
        percents: list[int] = []

        mock_result = ElementResult(name="btn", bbox=(100, 100, 50, 30), confidence=0.9, strategy="test")

        with patch("subprocess.Popen"), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full", return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text", return_value=mock_result), \
             patch("execution.action_engine.ActionEngine.click"):
            run_software_installer(pkg, lambda s, p: percents.append(p), stop_event)

        assert len(percents) == len(INSTALL_STEPS)
        assert percents == sorted(percents)
        assert percents[-1] == 100

    def test_action_engine_click_called_with_center_coords(self, tmp_path):
        """ActionEngine.click 被调用时使用 bbox 中心坐标。"""
        pkg = tmp_path / "installer.exe"
        pkg.write_bytes(b"fake")
        stop_event = threading.Event()

        # bbox = (x=100, y=200, w=60, h=40) → center = (130, 220)
        mock_result = ElementResult(name="btn", bbox=(100, 200, 60, 40), confidence=0.9, strategy="test")

        with patch("subprocess.Popen"), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full", return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text", return_value=mock_result), \
             patch("execution.action_engine.ActionEngine.click") as mock_click:
            # Only run 1 step to check coords
            single_step = [INSTALL_STEPS[0]]
            with patch("automation.software_installer.INSTALL_STEPS", single_step):
                run_software_installer(pkg, lambda s, p: None, stop_event)

        # cx = 100 + 60//2 = 130, cy = 200 + 40//2 = 220
        mock_click.assert_called_once_with(130, 220)
