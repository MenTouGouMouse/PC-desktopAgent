"""
Integration tests for path resolution in ChatAgent and PythonAPI.

**Validates: Requirements 2.1, 2.2, 3.2, 3.3, 3.4**

Tests:
1. ChatAgent._run_file_organizer resolves Chinese aliases before calling run_file_organizer
2. PythonAPI.start_file_organizer resolves a foreign-user path from settings
3. run_file_organizer still raises FileNotFoundError for a non-existent resolved path
"""
from __future__ import annotations

import threading
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gui.chat_agent import ChatAgent
from gui.progress_manager import ProgressManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def progress_manager() -> ProgressManager:
    return ProgressManager()


@pytest.fixture()
def stop_event() -> threading.Event:
    return threading.Event()


@pytest.fixture()
def push_fn() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def chat_agent(progress_manager: ProgressManager, stop_event: threading.Event, push_fn: MagicMock) -> ChatAgent:
    llm_client = MagicMock()
    return ChatAgent(
        llm_client=llm_client,
        progress_manager=progress_manager,
        stop_event=stop_event,
        push_fn=push_fn,
    )


# ---------------------------------------------------------------------------
# Test 1: ChatAgent resolves Chinese aliases before calling run_file_organizer
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_chat_agent_resolves_chinese_aliases(
    chat_agent: ChatAgent,
) -> None:
    """_run_file_organizer with source='桌面', target='下载' must call
    run_file_organizer with Path.home()/'Desktop' and Path.home()/'Downloads'."""
    expected_source = str(Path.home() / "Desktop")
    expected_target = str(Path.home() / "Downloads")

    with patch("automation.file_organizer.run_file_organizer") as mock_run:
        mock_run.return_value = None
        chat_agent._run_file_organizer({"source": "桌面", "target": "下载"})

    mock_run.assert_called_once()
    call_args = mock_run.call_args
    actual_source = call_args.args[0]
    actual_target = call_args.args[1]

    assert actual_source == expected_source, (
        f"Expected source={expected_source!r}, got {actual_source!r}"
    )
    assert actual_target == expected_target, (
        f"Expected target={expected_target!r}, got {actual_target!r}"
    )


@pytest.mark.integration
def test_chat_agent_resolves_english_aliases(
    chat_agent: ChatAgent,
) -> None:
    """_run_file_organizer with source='Desktop', target='Documents' resolves correctly."""
    expected_source = str(Path.home() / "Desktop")
    expected_target = str(Path.home() / "Documents")

    with patch("automation.file_organizer.run_file_organizer") as mock_run:
        mock_run.return_value = None
        chat_agent._run_file_organizer({"source": "Desktop", "target": "Documents"})

    call_args = mock_run.call_args
    assert call_args.args[0] == expected_source
    assert call_args.args[1] == expected_target


# ---------------------------------------------------------------------------
# Test 2: PythonAPI.start_file_organizer resolves a foreign-user path from settings
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_python_api_resolves_foreign_user_path_from_settings() -> None:
    """start_file_organizer must resolve a foreign-user path read from settings."""
    from gui.app import PythonAPI
    from gui.progress_manager import ProgressManager
    from ui.queue_manager import QueueManager

    pm = ProgressManager()
    qm = QueueManager()
    api = PythonAPI(pm, qm)

    foreign_source = "C:\\Users\\__foreign_user__\\Downloads"
    foreign_target = "C:\\Users\\__foreign_user__\\Organized"

    expected_source = str(Path.home() / "Downloads")
    # Organized is not in ALIAS_MAP, so only the user part is re-rooted
    expected_target = str(Path.home() / "Organized")

    def _fake_get_setting(key: str, default: str = "") -> str:
        if key == "file_organizer.source_dir":
            return foreign_source
        if key == "file_organizer.target_dir":
            return foreign_target
        return default

    api._get_setting = _fake_get_setting  # type: ignore[method-assign]

    with patch("gui.app.run_file_organizer") as mock_run:
        mock_run.return_value = None
        result = api.start_file_organizer()

    assert result["success"] is True

    # Wait briefly for the background thread to call run_file_organizer
    import time
    for _ in range(20):
        if mock_run.called:
            break
        time.sleep(0.05)

    assert mock_run.called, "run_file_organizer was not called"
    call_args = mock_run.call_args
    actual_source = call_args.args[0]
    actual_target = call_args.args[1]

    assert actual_source == expected_source, (
        f"Expected source={expected_source!r}, got {actual_source!r}"
    )
    assert actual_target == expected_target, (
        f"Expected target={expected_target!r}, got {actual_target!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: run_file_organizer still raises FileNotFoundError for non-existent path
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_run_file_organizer_raises_for_nonexistent_resolved_path() -> None:
    """After resolution, if the resolved path does not exist, FileNotFoundError is raised."""
    from automation.file_organizer import run_file_organizer

    # Use a path that is absolute, not an alias, and guaranteed not to exist
    nonexistent = str(Path.home() / "__nonexistent_test_dir_xyz__")
    stop = threading.Event()

    with tempfile.TemporaryDirectory() as tmp_target:
        with pytest.raises(FileNotFoundError):
            run_file_organizer(nonexistent, tmp_target, lambda s, p: None, stop)
