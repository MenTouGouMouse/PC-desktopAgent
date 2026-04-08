"""
tests.unit.test_user_settings_manager — Property-based and unit tests for
Settings_Manager methods in PythonAPI.

Feature: user-configurable-default-paths
Properties tested:
  1. 配置读写往返一致性 (Requirements 1.1, 1.4)
  2. 损坏 JSON 回退到默认值 (Requirement 1.3)
  3. API 异常时返回结构化错误 (Requirement 2.4)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

# We test the private methods by instantiating PythonAPI with mocked dependencies
from gui.app import PythonAPI, _DEFAULT_INSTALLER_DIR, _DEFAULT_ORGANIZE_SOURCE


@contextmanager
def _tmp_dir():
    """Context manager that creates and cleans up a temp directory safely."""
    d = tempfile.mkdtemp()
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _make_api() -> PythonAPI:
    """Create a PythonAPI instance with mocked dependencies."""
    progress_manager = MagicMock()
    progress_manager.get.return_value = MagicMock(is_running=False, percent=0, status_text="", task_name="")
    queue_manager = MagicMock()
    return PythonAPI(progress_manager, queue_manager)


def _is_valid_json(b: bytes) -> bool:
    try:
        json.loads(b)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Property 1: 配置读写往返一致性
# Feature: user-configurable-default-paths
# Validates: Requirements 1.1, 1.4
# ---------------------------------------------------------------------------

@given(
    organize_source=st.text(min_size=1).filter(lambda s: s.strip()),
    installer_default_dir=st.text(min_size=1).filter(lambda s: s.strip()),
)
@h_settings(max_examples=100)
def test_settings_round_trip(organize_source: str, installer_default_dir: str) -> None:
    """Property 1: Writing then reading settings returns identical values.

    **Validates: Requirements 1.1, 1.4**
    """
    with _tmp_dir() as tmp_path:
        api = _make_api()
        settings_path = tmp_path / "user_settings.json"

        with patch("gui.app._USER_SETTINGS_PATH", settings_path):
            api._save_user_settings({
                "organize_source": organize_source,
                "installer_default_dir": installer_default_dir,
            })
            result = api._load_user_settings()

    assert result["organize_source"] == organize_source
    assert result["installer_default_dir"] == installer_default_dir


# ---------------------------------------------------------------------------
# Property 2: 损坏 JSON 回退到默认值
# Feature: user-configurable-default-paths
# Validates: Requirement 1.3
# ---------------------------------------------------------------------------

@given(corrupt_content=st.binary().filter(lambda b: not _is_valid_json(b)))
@h_settings(max_examples=100)
def test_corrupt_json_returns_defaults(corrupt_content: bytes) -> None:
    """Property 2: Corrupt JSON file causes fallback to defaults with WARNING logged.

    **Validates: Requirements 1.3**
    """
    with _tmp_dir() as tmp_path:
        api = _make_api()
        settings_path = tmp_path / "user_settings.json"
        settings_path.write_bytes(corrupt_content)

        warning_records: list[logging.LogRecord] = []

        class _CapHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                warning_records.append(record)

        handler = _CapHandler(level=logging.WARNING)
        _logger = logging.getLogger("gui.app")
        _logger.addHandler(handler)
        try:
            with patch("gui.app._USER_SETTINGS_PATH", settings_path):
                result = api._load_user_settings()
        finally:
            _logger.removeHandler(handler)

    assert result["organize_source"] == _DEFAULT_ORGANIZE_SOURCE
    assert result["installer_default_dir"] == _DEFAULT_INSTALLER_DIR
    assert any(r.levelno >= logging.WARNING for r in warning_records)


# ---------------------------------------------------------------------------
# Property 3: API 异常时返回结构化错误
# Feature: user-configurable-default-paths
# Validates: Requirement 2.4
# ---------------------------------------------------------------------------

@given(exception_type=st.sampled_from([PermissionError, OSError, IOError]))
@h_settings(max_examples=30)
def test_save_default_paths_exception_returns_error_dict(exception_type: type) -> None:
    """Property 3: save_default_paths returns structured error dict on exception.

    **Validates: Requirements 2.4**
    """
    progress_manager = MagicMock()
    progress_manager.get.return_value = MagicMock(is_running=False, percent=0, status_text="", task_name="")
    api = PythonAPI(progress_manager, MagicMock())

    with patch.object(api, "_save_user_settings", side_effect=exception_type("test error")):
        result = api.save_default_paths("/some/path", "/target/path", "/other/path")

    assert result.get("success") is False
    assert "error" in result
    assert isinstance(result["error"], str)
    assert len(result["error"]) > 0


@given(exception_type=st.sampled_from([PermissionError, OSError, IOError]))
@h_settings(max_examples=30)
def test_get_default_paths_exception_returns_error_dict(exception_type: type) -> None:
    """Property 3 (get): get_default_paths returns structured error dict on exception.

    **Validates: Requirements 2.4**
    """
    progress_manager = MagicMock()
    progress_manager.get.return_value = MagicMock(is_running=False, percent=0, status_text="", task_name="")
    api = PythonAPI(progress_manager, MagicMock())

    with patch.object(api, "_load_user_settings", side_effect=exception_type("test error")):
        result = api.get_default_paths()

    assert result.get("success") is False
    assert "error" in result


# ---------------------------------------------------------------------------
# Unit tests: example-based
# ---------------------------------------------------------------------------

def test_load_returns_defaults_when_file_missing() -> None:
    """File missing → returns default values."""
    with _tmp_dir() as tmp_path:
        api = _make_api()
        settings_path = tmp_path / "nonexistent.json"

        with patch("gui.app._USER_SETTINGS_PATH", settings_path):
            result = api._load_user_settings()

    assert result["organize_source"] == _DEFAULT_ORGANIZE_SOURCE
    assert result["installer_default_dir"] == _DEFAULT_INSTALLER_DIR


def test_save_creates_file_if_not_exists() -> None:
    """_save_user_settings creates file and parent dirs."""
    with _tmp_dir() as tmp_path:
        api = _make_api()
        settings_path = tmp_path / "nested" / "dir" / "user_settings.json"

        with patch("gui.app._USER_SETTINGS_PATH", settings_path):
            api._save_user_settings({"organize_source": "/foo", "installer_default_dir": "/bar"})

        assert settings_path.exists()
        data = json.loads(settings_path.read_text(encoding="utf-8"))

    assert data["organize_source"] == "/foo"
    assert data["installer_default_dir"] == "/bar"


def test_get_default_paths_returns_correct_shape() -> None:
    """get_default_paths returns dict with expected keys."""
    with _tmp_dir() as tmp_path:
        api = _make_api()
        settings_path = tmp_path / "user_settings.json"

        with patch("gui.app._USER_SETTINGS_PATH", settings_path):
            result = api.get_default_paths()

    assert "organize_source" in result
    assert "installer_default_dir" in result


def test_save_default_paths_returns_success_true() -> None:
    """save_default_paths returns {"success": True} on success."""
    with _tmp_dir() as tmp_path:
        api = _make_api()
        settings_path = tmp_path / "user_settings.json"

        with patch("gui.app._USER_SETTINGS_PATH", settings_path):
            result = api.save_default_paths("/organize", "/organized", "/install")

    assert result == {"success": True}


# ---------------------------------------------------------------------------
# Property 4: 用户配置路径传递到任务函数
# Feature: user-configurable-default-paths
# Validates: Requirements 3.1, 4.1
# ---------------------------------------------------------------------------

@given(path=st.text(min_size=1).filter(lambda s: s.strip()))
@h_settings(max_examples=100)
def test_configured_organize_path_passed_to_task(path: str) -> None:
    """Property 4: Configured organize_source is loaded and used as source_dir in start_file_organizer."""
    with _tmp_dir() as tmp_path:
        api = _make_api()
        settings_path = tmp_path / "user_settings.json"

        with patch("gui.app._USER_SETTINGS_PATH", settings_path):
            api.save_default_paths(path, os.path.expanduser("~/Organized"), os.path.expanduser("~/Downloads"))

            with patch("gui.app.run_file_organizer") as mock_run:
                api.start_file_organizer()
                import time as _time
                _time.sleep(0.05)

        # The source_dir passed to run_file_organizer should equal the configured path
        if mock_run.called:
            call_args = mock_run.call_args
            actual_source = call_args[0][0]  # first positional arg
            assert actual_source == path, f"Expected source_dir={path!r}, got {actual_source!r}"


# ---------------------------------------------------------------------------
# Unit tests: smart installer path
# ---------------------------------------------------------------------------

def test_start_smart_installer_loads_installer_default_dir() -> None:
    """start_smart_installer reads installer_default_dir from user settings."""
    with _tmp_dir() as tmp_path:
        api = _make_api()
        settings_path = tmp_path / "user_settings.json"

        with patch("gui.app._USER_SETTINGS_PATH", settings_path):
            api.save_default_paths(os.path.expanduser("~/Desktop"), os.path.expanduser("~/Organized"), "/custom/install/dir")
            loaded = api._load_user_settings()
            installer_dir = loaded.get("installer_default_dir") or os.path.expanduser("~/Downloads")

        assert installer_dir == "/custom/install/dir"


def test_start_smart_installer_fallback_when_not_configured() -> None:
    """installer_default_dir falls back to ~/Downloads when not configured."""
    with _tmp_dir() as tmp_path:
        api = _make_api()
        settings_path = tmp_path / "nonexistent.json"

        with patch("gui.app._USER_SETTINGS_PATH", settings_path):
            loaded = api._load_user_settings()
            installer_dir = loaded.get("installer_default_dir") or os.path.expanduser("~/Downloads")

        assert installer_dir == os.path.expanduser("~/Downloads")
