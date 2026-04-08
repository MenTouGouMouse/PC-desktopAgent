"""Unit tests for task/flow_recorder.py -- FlowRecorder."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from task.flow_recorder import FlowRecorder


def _make_recorder() -> FlowRecorder:
    return FlowRecorder()


class TestFlowRecorderLifecycle:
    def test_start_sets_recording_state(self) -> None:
        recorder = _make_recorder()
        with patch("task.flow_recorder.mouse.Listener"), \
             patch("task.flow_recorder.keyboard.Listener"):
            recorder.start("test_session")
            assert recorder._recording is True
            recorder._recording = False
            recorder._mouse_listener = None
            recorder._keyboard_listener = None

    def test_stop_clears_recording_state(self) -> None:
        recorder = _make_recorder()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("task.flow_recorder.mouse.Listener"), \
                 patch("task.flow_recorder.keyboard.Listener"), \
                 patch("task.flow_recorder.RECORDINGS_DIR", Path(tmp)):
                recorder.start("test_session")
                recorder.stop()
                assert recorder._recording is False

    def test_stop_without_start_raises(self) -> None:
        recorder = _make_recorder()
        with pytest.raises(RuntimeError, match="not currently recording"):
            recorder.stop()

    def test_double_start_is_ignored(self) -> None:
        recorder = _make_recorder()
        with patch("task.flow_recorder.mouse.Listener") as mock_mouse, \
             patch("task.flow_recorder.keyboard.Listener") as mock_kb:
            recorder.start("first")
            recorder.start("second")
            assert mock_mouse.call_count == 1
            assert mock_kb.call_count == 1
            recorder._recording = False
            recorder._mouse_listener = None
            recorder._keyboard_listener = None


class TestFlowRecorderFileOutput:
    def test_stop_returns_file_path(self) -> None:
        recorder = _make_recorder()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("task.flow_recorder.mouse.Listener"), \
                 patch("task.flow_recorder.keyboard.Listener"), \
                 patch("task.flow_recorder.RECORDINGS_DIR", Path(tmp)):
                recorder.start("my_flow")
                path = recorder.stop()
                assert path.startswith(tmp)
                assert "my_flow" in path
                assert path.endswith(".json")

    def test_stop_creates_valid_json_file(self) -> None:
        recorder = _make_recorder()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("task.flow_recorder.mouse.Listener"), \
                 patch("task.flow_recorder.keyboard.Listener"), \
                 patch("task.flow_recorder.RECORDINGS_DIR", Path(tmp)):
                recorder.start("my_flow")
                path = recorder.stop()
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                assert "version" in data
                assert "name" in data
                assert "created_at" in data
                assert "steps" in data

    def test_stop_file_name_contains_timestamp(self) -> None:
        recorder = _make_recorder()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("task.flow_recorder.mouse.Listener"), \
                 patch("task.flow_recorder.keyboard.Listener"), \
                 patch("task.flow_recorder.RECORDINGS_DIR", Path(tmp)):
                recorder.start("flow_name")
                path = recorder.stop()
                filename = Path(path).name
                assert filename.startswith("flow_name_")
                assert filename.endswith(".json")

    def test_stop_creates_recordings_dir_if_missing(self) -> None:
        recorder = _make_recorder()
        with tempfile.TemporaryDirectory() as tmp:
            new_dir = Path(tmp) / "new_recordings"
            assert not new_dir.exists()
            with patch("task.flow_recorder.mouse.Listener"), \
                 patch("task.flow_recorder.keyboard.Listener"), \
                 patch("task.flow_recorder.RECORDINGS_DIR", new_dir):
                recorder.start("test")
                recorder.stop()
                assert new_dir.exists()

    def test_stop_completes_within_2_seconds(self) -> None:
        recorder = _make_recorder()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("task.flow_recorder.mouse.Listener"), \
                 patch("task.flow_recorder.keyboard.Listener"), \
                 patch("task.flow_recorder.RECORDINGS_DIR", Path(tmp)):
                recorder.start("perf_test")
                t0 = time.monotonic()
                recorder.stop()
                elapsed = time.monotonic() - t0
                assert elapsed < 2.0, f"stop() took {elapsed:.2f}s, expected < 2s"


class TestFlowRecorderEvents:
    def _started_recorder(self) -> FlowRecorder:
        recorder = _make_recorder()
        with patch("task.flow_recorder.mouse.Listener"), \
             patch("task.flow_recorder.keyboard.Listener"):
            recorder.start("evt_test")
        return recorder

    def test_mouse_move_appends_step(self) -> None:
        recorder = self._started_recorder()
        recorder._on_mouse_move(100, 200)
        assert len(recorder._steps) == 1
        step = recorder._steps[0]
        assert step.action_type == "mouse_move"
        assert step.parameters == {"x": 100, "y": 200}
        recorder._recording = False

    def test_mouse_click_pressed_appends_step(self) -> None:
        recorder = self._started_recorder()
        from pynput.mouse import Button
        recorder._on_mouse_click(50, 75, Button.left, pressed=True)
        assert len(recorder._steps) == 1
        step = recorder._steps[0]
        assert step.action_type == "mouse_click"
        assert step.parameters == {"x": 50, "y": 75}
        recorder._recording = False

    def test_mouse_click_released_ignored(self) -> None:
        recorder = self._started_recorder()
        from pynput.mouse import Button
        recorder._on_mouse_click(50, 75, Button.left, pressed=False)
        assert len(recorder._steps) == 0
        recorder._recording = False

    def test_key_press_special_key_appends_key_press_step(self) -> None:
        recorder = self._started_recorder()
        from pynput.keyboard import Key
        recorder._on_key_press(Key.enter)
        assert len(recorder._steps) == 1
        step = recorder._steps[0]
        assert step.action_type == "key_press"
        assert step.parameters["key"] == "enter"
        recorder._recording = False

    def test_key_press_char_key_appends_type_text_step(self) -> None:
        recorder = self._started_recorder()
        from pynput.keyboard import KeyCode
        recorder._on_key_press(KeyCode.from_char("a"))
        assert len(recorder._steps) == 1
        step = recorder._steps[0]
        assert step.action_type == "type_text"
        assert step.parameters["text"] == "a"
        recorder._recording = False

    def test_events_not_recorded_when_stopped(self) -> None:
        recorder = _make_recorder()
        recorder._on_mouse_move(10, 20)
        assert len(recorder._steps) == 0

    def test_step_ids_are_sequential(self) -> None:
        recorder = self._started_recorder()
        from pynput.mouse import Button
        recorder._on_mouse_move(1, 2)
        recorder._on_mouse_click(3, 4, Button.left, pressed=True)
        recorder._on_mouse_move(5, 6)
        ids = [s.step_id for s in recorder._steps]
        assert ids == [1, 2, 3]
        recorder._recording = False

    def test_delay_ms_is_non_negative(self) -> None:
        recorder = self._started_recorder()
        recorder._on_mouse_move(10, 20)
        recorder._on_mouse_move(30, 40)
        for step in recorder._steps:
            assert step.delay_ms >= 0
        recorder._recording = False


class TestFlowRecorderSerialization:
    def test_recorded_steps_in_json(self) -> None:
        recorder = _make_recorder()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("task.flow_recorder.mouse.Listener"), \
                 patch("task.flow_recorder.keyboard.Listener"), \
                 patch("task.flow_recorder.RECORDINGS_DIR", Path(tmp)):
                recorder.start("serialize_test")
                from pynput.mouse import Button
                recorder._on_mouse_move(10, 20)
                recorder._on_mouse_click(30, 40, Button.left, pressed=True)
                path = recorder.stop()

            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)

        assert len(data["steps"]) == 2
        assert data["steps"][0]["action_type"] == "mouse_move"
        assert data["steps"][1]["action_type"] == "mouse_click"

    def test_saved_json_step_has_required_fields(self) -> None:
        recorder = _make_recorder()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("task.flow_recorder.mouse.Listener"), \
                 patch("task.flow_recorder.keyboard.Listener"), \
                 patch("task.flow_recorder.RECORDINGS_DIR", Path(tmp)):
                recorder.start("schema_test")
                recorder._on_mouse_move(5, 10)
                path = recorder.stop()

            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)

        step = data["steps"][0]
        assert "step_id" in step
        assert "action_type" in step
        assert "parameters" in step
        assert "delay_ms" in step

    def test_flow_template_name_matches_session_name(self) -> None:
        recorder = _make_recorder()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("task.flow_recorder.mouse.Listener"), \
                 patch("task.flow_recorder.keyboard.Listener"), \
                 patch("task.flow_recorder.RECORDINGS_DIR", Path(tmp)):
                recorder.start("my_session")
                path = recorder.stop()

            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)

        assert data["name"] == "my_session"
