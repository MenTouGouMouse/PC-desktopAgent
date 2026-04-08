"""任务层集成测试：FlowRecorder → FlowExecutor 往返。

测试 FlowRecorder 录制的 JSON 文件能被 FlowExecutor 正确加载并回放，
验证录制与回放模块之间的数据格式契约（Flow_Template JSON Schema）。

使用 tests/fixtures/flow_templates/ 中的预置 JSON 文件作为 fixture，
mock 所有外部 I/O（pynput 监听器、pyautogui、pyperclip），不产生真实操作。

Requirements: 8.2, 9.1
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from task.flow_executor import ExecutionReport, FlowExecutor
from task.flow_recorder import FlowRecorder
from task.flow_schema import FlowTemplate, Step

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "flow_templates"
SIMPLE_CLICK_FLOW = FIXTURES_DIR / "simple_click_flow.json"
KEYBOARD_FLOW = FIXTURES_DIR / "keyboard_flow.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_engine(
    click: bool = True,
    move_to: bool = True,
    type_text: bool = True,
    key_press: bool = True,
) -> MagicMock:
    engine = MagicMock()
    engine.click.return_value = click
    engine.move_to.return_value = move_to
    engine.type_text.return_value = type_text
    engine.key_press.return_value = key_press
    return engine


def _record_steps(recorder: FlowRecorder, tmp_dir: Path) -> str:
    """Start recorder, inject synthetic events, stop and return file path."""
    from pynput.keyboard import Key, KeyCode
    from pynput.mouse import Button

    with (
        patch("task.flow_recorder.mouse.Listener"),
        patch("task.flow_recorder.keyboard.Listener"),
        patch("task.flow_recorder.RECORDINGS_DIR", tmp_dir),
    ):
        recorder.start("integration_test")
        recorder._on_mouse_move(100, 200)
        recorder._on_mouse_click(300, 400, Button.left, pressed=True)
        recorder._on_key_press(KeyCode.from_char("h"))
        recorder._on_key_press(KeyCode.from_char("i"))
        recorder._on_key_press(Key.enter)
        return recorder.stop()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFlowRecorderToExecutorRoundTrip:
    """FlowRecorder → FlowExecutor 往返集成测试。

    Validates: Requirements 8.2, 9.1
    """

    def test_recorder_output_passes_schema_validation(self) -> None:
        """FlowRecorder.stop() 生成的 JSON 必须通过 FlowExecutor.load() 的 schema 验证。

        Validates: Requirements 8.2, 9.1
        """
        recorder = FlowRecorder()
        executor = FlowExecutor(action_engine=_make_mock_engine())

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = _record_steps(recorder, tmp_path)

            # FlowExecutor.load 内部做 jsonschema 验证，不抛出即为通过
            template = executor.load(file_path)

        assert template is not None
        assert template.name == "integration_test"
        assert len(template.steps) == 5  # move + click + h + i + enter

    def test_recorder_output_can_be_replayed_successfully(self) -> None:
        """FlowRecorder 录制的文件能被 FlowExecutor 完整回放。

        Validates: Requirements 8.2, 9.1
        """
        recorder = FlowRecorder()
        engine = _make_mock_engine()
        executor = FlowExecutor(action_engine=engine)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = _record_steps(recorder, tmp_path)

            with patch("time.sleep"):
                template = executor.load(file_path)
                report = executor.run(template)

        assert report.success is True
        assert len(report.completed_steps) == 5

    def test_recorder_step_types_preserved_through_roundtrip(self) -> None:
        """录制的 action_type 在序列化/反序列化后保持不变。

        Validates: Requirements 8.2
        """
        recorder = FlowRecorder()
        executor = FlowExecutor(action_engine=_make_mock_engine())

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = _record_steps(recorder, tmp_path)
            template = executor.load(file_path)

        action_types = [s.action_type for s in template.steps]
        assert "mouse_move" in action_types
        assert "mouse_click" in action_types
        assert "type_text" in action_types
        assert "key_press" in action_types

    def test_recorder_step_parameters_preserved_through_roundtrip(self) -> None:
        """录制的坐标和文本参数在往返后保持一致。

        Validates: Requirements 8.2
        """
        recorder = FlowRecorder()
        executor = FlowExecutor(action_engine=_make_mock_engine())

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = _record_steps(recorder, tmp_path)
            template = executor.load(file_path)

        move_step = next(s for s in template.steps if s.action_type == "mouse_move")
        assert move_step.parameters["x"] == 100
        assert move_step.parameters["y"] == 200

        click_step = next(s for s in template.steps if s.action_type == "mouse_click")
        assert click_step.parameters["x"] == 300
        assert click_step.parameters["y"] == 400

    def test_recorder_step_ids_are_sequential_after_roundtrip(self) -> None:
        """往返后 step_id 保持连续递增。

        Validates: Requirements 8.2
        """
        recorder = FlowRecorder()
        executor = FlowExecutor(action_engine=_make_mock_engine())

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = _record_steps(recorder, tmp_path)
            template = executor.load(file_path)

        ids = sorted(s.step_id for s in template.steps)
        assert ids == list(range(1, len(ids) + 1))

    def test_recorder_delay_ms_non_negative_after_roundtrip(self) -> None:
        """往返后所有步骤的 delay_ms 均为非负整数。

        Validates: Requirements 8.2
        """
        recorder = FlowRecorder()
        executor = FlowExecutor(action_engine=_make_mock_engine())

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = _record_steps(recorder, tmp_path)
            template = executor.load(file_path)

        for step in template.steps:
            assert isinstance(step.delay_ms, int)
            assert step.delay_ms >= 0

    def test_executor_calls_action_engine_with_recorded_coordinates(self) -> None:
        """FlowExecutor 回放时，ActionEngine 收到的坐标与录制时一致。

        Validates: Requirements 9.1
        """
        recorder = FlowRecorder()
        engine = _make_mock_engine()
        executor = FlowExecutor(action_engine=engine)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = _record_steps(recorder, tmp_path)

            with patch("time.sleep"):
                template = executor.load(file_path)
                executor.run(template)

        # Verify move_to was called with the recorded coordinates
        engine.move_to.assert_any_call(x=100, y=200)
        # Verify click was called with the recorded coordinates
        engine.click.assert_any_call(x=300, y=400, click_type="single")

    def test_executor_calls_type_text_for_char_keys(self) -> None:
        """录制的字符按键（type_text）被 FlowExecutor 正确路由到 type_text。

        Validates: Requirements 9.1
        """
        recorder = FlowRecorder()
        engine = _make_mock_engine()
        executor = FlowExecutor(action_engine=engine)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = _record_steps(recorder, tmp_path)

            with patch("time.sleep"):
                template = executor.load(file_path)
                executor.run(template)

        # "h" and "i" are recorded as type_text
        type_text_calls = [str(c) for c in engine.type_text.call_args_list]
        assert any("h" in c for c in type_text_calls)
        assert any("i" in c for c in type_text_calls)

    def test_executor_calls_key_press_for_special_keys(self) -> None:
        """录制的特殊按键（key_press）被 FlowExecutor 正确路由到 key_press。

        Validates: Requirements 9.1
        """
        recorder = FlowRecorder()
        engine = _make_mock_engine()
        executor = FlowExecutor(action_engine=engine)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = _record_steps(recorder, tmp_path)

            with patch("time.sleep"):
                template = executor.load(file_path)
                executor.run(template)

        engine.key_press.assert_any_call(key="enter")


@pytest.mark.integration
class TestFixtureFlowTemplates:
    """使用 tests/fixtures/flow_templates/ 中的预置 JSON 文件测试 FlowExecutor。

    Validates: Requirements 9.1
    """

    def test_load_simple_click_flow_fixture(self) -> None:
        """simple_click_flow.json fixture 能被正确加载。"""
        executor = FlowExecutor(action_engine=_make_mock_engine())
        template = executor.load(str(SIMPLE_CLICK_FLOW))

        assert template.name == "simple_click_flow"
        assert template.version == "1.0"
        assert len(template.steps) == 3

    def test_run_simple_click_flow_fixture(self) -> None:
        """simple_click_flow.json fixture 能被完整回放。"""
        engine = _make_mock_engine()
        executor = FlowExecutor(action_engine=engine)

        with patch("time.sleep"):
            template = executor.load(str(SIMPLE_CLICK_FLOW))
            report = executor.run(template)

        assert report.success is True
        assert report.completed_steps == [1, 2, 3]

    def test_simple_click_flow_action_engine_calls(self) -> None:
        """simple_click_flow.json 回放时 ActionEngine 收到正确的调用。"""
        engine = _make_mock_engine()
        executor = FlowExecutor(action_engine=engine)

        with patch("time.sleep"):
            template = executor.load(str(SIMPLE_CLICK_FLOW))
            executor.run(template)

        engine.move_to.assert_called_once_with(x=100, y=200)
        engine.click.assert_called_once_with(x=100, y=200, click_type="single")
        engine.type_text.assert_called_once_with(text="hello")

    def test_load_keyboard_flow_fixture(self) -> None:
        """keyboard_flow.json fixture 能被正确加载。"""
        executor = FlowExecutor(action_engine=_make_mock_engine())
        template = executor.load(str(KEYBOARD_FLOW))

        assert template.name == "keyboard_flow"
        assert len(template.steps) == 3

    def test_run_keyboard_flow_fixture(self) -> None:
        """keyboard_flow.json fixture 能被完整回放。"""
        engine = _make_mock_engine()
        executor = FlowExecutor(action_engine=engine)

        with patch("time.sleep"):
            template = executor.load(str(KEYBOARD_FLOW))
            report = executor.run(template)

        assert report.success is True
        assert report.completed_steps == [1, 2, 3]

    def test_keyboard_flow_chinese_text_routed_to_type_text(self) -> None:
        """keyboard_flow.json 中的中文文本被正确路由到 type_text。"""
        engine = _make_mock_engine()
        executor = FlowExecutor(action_engine=engine)

        with patch("time.sleep"):
            template = executor.load(str(KEYBOARD_FLOW))
            executor.run(template)

        engine.type_text.assert_called_once_with(text="你好世界")

    def test_fixture_step_order_preserved(self) -> None:
        """fixture 中的步骤按 step_id 升序执行。"""
        call_order: list[str] = []
        engine = MagicMock()
        engine.move_to.side_effect = lambda **_: call_order.append("move_to") or True
        engine.click.side_effect = lambda **_: call_order.append("click") or True
        engine.type_text.side_effect = lambda **_: call_order.append("type_text") or True

        executor = FlowExecutor(action_engine=engine)

        with patch("time.sleep"):
            template = executor.load(str(SIMPLE_CLICK_FLOW))
            executor.run(template)

        assert call_order == ["move_to", "click", "type_text"]

    def test_fixture_delays_respected_during_replay(self) -> None:
        """fixture 中的 delay_ms 在回放时被传递给 time.sleep。"""
        engine = _make_mock_engine()
        executor = FlowExecutor(action_engine=engine)

        with patch("time.sleep") as mock_sleep:
            template = executor.load(str(SIMPLE_CLICK_FLOW))
            executor.run(template)

        # simple_click_flow has delay_ms: 50, 100, 0
        mock_sleep.assert_any_call(0.05)
        mock_sleep.assert_any_call(0.1)
        # delay_ms=0 should NOT trigger sleep
        assert mock_sleep.call_count == 2


@pytest.mark.integration
class TestFlowExecutorFailureScenarios:
    """FlowExecutor 回放失败场景的集成测试。

    Validates: Requirements 9.1
    """

    def test_replay_stops_at_first_failed_step(self) -> None:
        """回放在第一个失败步骤后停止，不继续执行后续步骤。

        Validates: Requirements 9.1
        """
        engine = _make_mock_engine()
        engine.move_to.return_value = False  # step 1 fails

        executor = FlowExecutor(action_engine=engine)

        with patch("time.sleep"):
            template = executor.load(str(SIMPLE_CLICK_FLOW))
            report = executor.run(template)

        assert report.success is False
        assert report.failed_step_id == 1
        assert report.completed_steps == []
        # Steps 2 and 3 must NOT have been called
        engine.click.assert_not_called()
        engine.type_text.assert_not_called()

    def test_replay_reports_correct_failed_step_id(self) -> None:
        """失败报告中的 failed_step_id 与实际失败步骤一致。

        Validates: Requirements 9.1
        """
        engine = _make_mock_engine()
        engine.click.return_value = False  # step 2 fails

        executor = FlowExecutor(action_engine=engine)

        with patch("time.sleep"):
            template = executor.load(str(SIMPLE_CLICK_FLOW))
            report = executor.run(template)

        assert report.success is False
        assert report.failed_step_id == 2
        assert report.completed_steps == [1]  # step 1 (move_to) succeeded

    def test_replay_failure_reason_is_non_empty(self) -> None:
        """失败报告中的 reason 字段不为空。

        Validates: Requirements 9.1
        """
        engine = _make_mock_engine()
        engine.type_text.return_value = False  # step 3 fails

        executor = FlowExecutor(action_engine=engine)

        with patch("time.sleep"):
            template = executor.load(str(SIMPLE_CLICK_FLOW))
            report = executor.run(template)

        assert report.success is False
        assert report.reason != ""

    def test_load_invalid_json_does_not_execute(self) -> None:
        """加载无效 JSON 时不执行任何 ActionEngine 操作。

        Validates: Requirements 9.1
        """
        from jsonschema import ValidationError

        engine = _make_mock_engine()
        executor = FlowExecutor(action_engine=engine)

        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "bad.json"
            bad_path.write_text(
                json.dumps({"version": "1.0", "name": "x", "created_at": "2024-01-01T00:00:00Z"}),
                encoding="utf-8",
            )
            with pytest.raises(ValidationError):
                executor.load(str(bad_path))

        engine.click.assert_not_called()
        engine.move_to.assert_not_called()
        engine.type_text.assert_not_called()
        engine.key_press.assert_not_called()
