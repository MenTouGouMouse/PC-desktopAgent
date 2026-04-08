"""Unit tests for task/flow_executor.py — FlowExecutor and ExecutionReport."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from jsonschema import ValidationError

from task.flow_executor import ExecutionReport, FlowExecutor
from task.flow_schema import FlowTemplate, Step

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_step(
    step_id: int = 1,
    action_type: str = "mouse_click",
    parameters: dict | None = None,
    delay_ms: int = 0,
) -> Step:
    if parameters is None:
        if action_type in ("mouse_click", "mouse_move"):
            parameters = {"x": 100, "y": 200}
        elif action_type == "key_press":
            parameters = {"key": "enter"}
        else:
            parameters = {"text": "hello"}
    return Step(step_id=step_id, action_type=action_type, parameters=parameters, delay_ms=delay_ms)


def _make_template(steps: list[Step] | None = None, name: str = "test_flow") -> FlowTemplate:
    return FlowTemplate(
        version="1.0",
        name=name,
        created_at="2024-01-01T00:00:00Z",
        steps=[_make_step()] if steps is None else steps,
    )


def _write_template_file(tmp_dir: str, template: FlowTemplate, filename: str = "flow.json") -> str:
    path = Path(tmp_dir) / filename
    path.write_text(json.dumps(template.to_dict()), encoding="utf-8")
    return str(path)


def _make_executor(engine: MagicMock | None = None) -> FlowExecutor:
    """Create a FlowExecutor with a mocked ActionEngine."""
    if engine is None:
        engine = MagicMock()
        engine.click.return_value = True
        engine.move_to.return_value = True
        engine.type_text.return_value = True
    return FlowExecutor(action_engine=engine)


# ---------------------------------------------------------------------------
# ExecutionReport dataclass
# ---------------------------------------------------------------------------

class TestExecutionReport:
    def test_success_report_defaults(self) -> None:
        report = ExecutionReport(success=True, completed_steps=[1, 2, 3])
        assert report.success is True
        assert report.failed_step_id is None
        assert report.reason == ""
        assert report.completed_steps == [1, 2, 3]

    def test_failure_report_fields(self) -> None:
        report = ExecutionReport(
            success=False,
            failed_step_id=2,
            reason="click returned False",
            completed_steps=[1],
        )
        assert report.success is False
        assert report.failed_step_id == 2
        assert report.reason == "click returned False"
        assert report.completed_steps == [1]

    def test_default_completed_steps_is_empty_list(self) -> None:
        report = ExecutionReport(success=True)
        assert report.completed_steps == []


# ---------------------------------------------------------------------------
# FlowExecutor.load
# ---------------------------------------------------------------------------

class TestFlowExecutorLoad:
    def test_load_valid_file_returns_template(self) -> None:
        executor = _make_executor()
        template = _make_template()
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_template_file(tmp, template)
            loaded = executor.load(path)
        assert loaded.name == "test_flow"
        assert loaded.version == "1.0"
        assert len(loaded.steps) == 1

    def test_load_preserves_all_steps(self) -> None:
        executor = _make_executor()
        steps = [
            _make_step(1, "mouse_click"),
            _make_step(2, "mouse_move"),
            _make_step(3, "key_press"),
            _make_step(4, "type_text"),
        ]
        template = _make_template(steps=steps)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_template_file(tmp, template)
            loaded = executor.load(path)
        assert len(loaded.steps) == 4
        assert [s.step_id for s in loaded.steps] == [1, 2, 3, 4]

    def test_load_missing_file_raises_file_not_found(self) -> None:
        executor = _make_executor()
        with pytest.raises(FileNotFoundError):
            executor.load("/nonexistent/path/flow.json")

    def test_load_invalid_json_raises_decode_error(self) -> None:
        executor = _make_executor()
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "bad.json"
            bad_path.write_text("not valid json {{{", encoding="utf-8")
            with pytest.raises(json.JSONDecodeError):
                executor.load(str(bad_path))

    def test_load_schema_invalid_raises_validation_error(self) -> None:
        executor = _make_executor()
        # Missing required 'steps' field
        bad_data = {"version": "1.0", "name": "x", "created_at": "2024-01-01T00:00:00Z"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(bad_data), encoding="utf-8")
            with pytest.raises(ValidationError):
                executor.load(str(path))

    def test_load_schema_invalid_wrong_step_type_raises(self) -> None:
        executor = _make_executor()
        bad_data = {
            "version": "1.0",
            "name": "x",
            "created_at": "2024-01-01T00:00:00Z",
            "steps": [
                {
                    "step_id": 1,
                    "action_type": "unknown_action",  # not in enum
                    "parameters": {},
                    "delay_ms": 0,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(bad_data), encoding="utf-8")
            with pytest.raises(ValidationError):
                executor.load(str(path))

    def test_load_empty_steps_is_valid(self) -> None:
        executor = _make_executor()
        template = FlowTemplate(
            version="1.0", name="empty", created_at="2024-01-01T00:00:00Z", steps=[]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_template_file(tmp, template)
            loaded = executor.load(path)
        assert loaded.steps == []


# ---------------------------------------------------------------------------
# FlowExecutor.run — success paths
# ---------------------------------------------------------------------------

class TestFlowExecutorRunSuccess:
    def test_run_mouse_click_step_succeeds(self) -> None:
        engine = MagicMock()
        engine.click.return_value = True
        executor = _make_executor(engine)
        template = _make_template(steps=[_make_step(1, "mouse_click", {"x": 50, "y": 60})])
        report = executor.run(template)
        assert report.success is True
        assert report.completed_steps == [1]
        engine.click.assert_called_once_with(x=50, y=60, click_type="single")

    def test_run_mouse_move_step_succeeds(self) -> None:
        engine = MagicMock()
        engine.move_to.return_value = True
        executor = _make_executor(engine)
        template = _make_template(steps=[_make_step(1, "mouse_move", {"x": 10, "y": 20})])
        report = executor.run(template)
        assert report.success is True
        engine.move_to.assert_called_once_with(x=10, y=20)

    def test_run_type_text_step_succeeds(self) -> None:
        engine = MagicMock()
        engine.type_text.return_value = True
        executor = _make_executor(engine)
        template = _make_template(steps=[_make_step(1, "type_text", {"text": "hello"})])
        report = executor.run(template)
        assert report.success is True
        engine.type_text.assert_called_once_with(text="hello")

    def test_run_key_press_step_succeeds(self) -> None:
        engine = MagicMock()
        engine.key_press.return_value = True
        executor = _make_executor(engine)
        template = _make_template(steps=[_make_step(1, "key_press", {"key": "enter"})])
        report = executor.run(template)
        assert report.success is True
        engine.key_press.assert_called_once_with(key="enter")

    def test_run_multiple_steps_all_succeed(self) -> None:
        engine = MagicMock()
        engine.click.return_value = True
        engine.move_to.return_value = True
        engine.type_text.return_value = True
        executor = _make_executor(engine)
        steps = [
            _make_step(1, "mouse_move", {"x": 1, "y": 2}),
            _make_step(2, "mouse_click", {"x": 3, "y": 4}),
            _make_step(3, "type_text", {"text": "abc"}),
        ]
        template = _make_template(steps=steps)
        report = executor.run(template)
        assert report.success is True
        assert report.completed_steps == [1, 2, 3]

    def test_run_empty_template_returns_success(self) -> None:
        executor = _make_executor()
        template = _make_template(steps=[])
        report = executor.run(template)
        assert report.success is True
        assert report.completed_steps == []

    def test_run_steps_executed_in_step_id_order(self) -> None:
        """Steps must be sorted by step_id regardless of list order."""
        call_order: list[int] = []
        engine = MagicMock()
        engine.click.side_effect = lambda **_: call_order.append("click") or True
        engine.move_to.side_effect = lambda **_: call_order.append("move") or True
        executor = _make_executor(engine)
        # Provide steps out of order
        steps = [
            _make_step(3, "mouse_click", {"x": 1, "y": 2}),
            _make_step(1, "mouse_move", {"x": 3, "y": 4}),
            _make_step(2, "mouse_click", {"x": 5, "y": 6}),
        ]
        template = _make_template(steps=steps)
        report = executor.run(template)
        assert report.success is True
        assert report.completed_steps == [1, 2, 3]
        assert call_order == ["move", "click", "click"]

    def test_run_mouse_click_with_click_type(self) -> None:
        engine = MagicMock()
        engine.click.return_value = True
        executor = _make_executor(engine)
        template = _make_template(
            steps=[_make_step(1, "mouse_click", {"x": 10, "y": 20, "click_type": "double"})]
        )
        report = executor.run(template)
        assert report.success is True
        engine.click.assert_called_once_with(x=10, y=20, click_type="double")


# ---------------------------------------------------------------------------
# FlowExecutor.run — failure paths
# ---------------------------------------------------------------------------

class TestFlowExecutorRunFailure:
    def test_run_click_returns_false_stops_execution(self) -> None:
        engine = MagicMock()
        engine.click.return_value = False
        executor = _make_executor(engine)
        steps = [
            _make_step(1, "mouse_click", {"x": 10, "y": 20}),
            _make_step(2, "mouse_click", {"x": 30, "y": 40}),
        ]
        template = _make_template(steps=steps)
        report = executor.run(template)
        assert report.success is False
        assert report.failed_step_id == 1
        assert report.completed_steps == []
        # Step 2 must NOT have been called
        assert engine.click.call_count == 1

    def test_run_move_to_returns_false_stops_execution(self) -> None:
        engine = MagicMock()
        engine.move_to.return_value = False
        executor = _make_executor(engine)
        template = _make_template(steps=[_make_step(1, "mouse_move", {"x": 5, "y": 5})])
        report = executor.run(template)
        assert report.success is False
        assert report.failed_step_id == 1

    def test_run_type_text_returns_false_stops_execution(self) -> None:
        engine = MagicMock()
        engine.type_text.return_value = False
        executor = _make_executor(engine)
        template = _make_template(steps=[_make_step(1, "type_text", {"text": "hi"})])
        report = executor.run(template)
        assert report.success is False
        assert report.failed_step_id == 1

    def test_run_unknown_action_type_returns_failure(self) -> None:
        executor = _make_executor()
        step = Step(step_id=1, action_type="mouse_click", parameters={"x": 1, "y": 2}, delay_ms=0)
        # Manually override action_type to something unknown after construction
        step.action_type = "unknown_action"  # type: ignore[assignment]
        template = _make_template(steps=[step])
        report = executor.run(template)
        assert report.success is False
        assert report.failed_step_id == 1
        assert "unknown_action" in report.reason

    def test_run_exception_in_step_returns_failure(self) -> None:
        engine = MagicMock()
        engine.click.side_effect = RuntimeError("hardware error")
        executor = _make_executor(engine)
        template = _make_template(steps=[_make_step(1, "mouse_click")])
        report = executor.run(template)
        assert report.success is False
        assert report.failed_step_id == 1
        assert "hardware error" in report.reason

    def test_run_failure_reports_completed_steps_before_failure(self) -> None:
        engine = MagicMock()
        # Step 1 and 2 succeed, step 3 fails
        call_count = [0]

        def click_side_effect(**kwargs: object) -> bool:
            call_count[0] += 1
            return call_count[0] < 3  # True for calls 1 and 2, False for call 3

        engine.click.side_effect = click_side_effect
        executor = _make_executor(engine)
        steps = [_make_step(i, "mouse_click", {"x": i, "y": i}) for i in range(1, 4)]
        template = _make_template(steps=steps)
        report = executor.run(template)
        assert report.success is False
        assert report.failed_step_id == 3
        assert report.completed_steps == [1, 2]

    def test_run_failure_reason_contains_coordinates(self) -> None:
        engine = MagicMock()
        engine.click.return_value = False
        executor = _make_executor(engine)
        template = _make_template(steps=[_make_step(1, "mouse_click", {"x": 42, "y": 99})])
        report = executor.run(template)
        assert "42" in report.reason
        assert "99" in report.reason


# ---------------------------------------------------------------------------
# FlowExecutor.run — delay behaviour
# ---------------------------------------------------------------------------

class TestFlowExecutorDelay:
    def test_run_no_delay_when_delay_ms_zero(self) -> None:
        executor = _make_executor()
        template = _make_template(steps=[_make_step(1, "mouse_click", delay_ms=0)])
        with patch("time.sleep") as mock_sleep:
            executor.run(template)
        mock_sleep.assert_not_called()

    def test_run_calls_sleep_for_positive_delay(self) -> None:
        executor = _make_executor()
        template = _make_template(steps=[_make_step(1, "mouse_click", delay_ms=500)])
        with patch("time.sleep") as mock_sleep:
            executor.run(template)
        mock_sleep.assert_called_once_with(0.5)

    def test_run_sleep_called_between_steps(self) -> None:
        engine = MagicMock()
        engine.click.return_value = True
        executor = _make_executor(engine)
        steps = [
            _make_step(1, "mouse_click", {"x": 1, "y": 1}, delay_ms=100),
            _make_step(2, "mouse_click", {"x": 2, "y": 2}, delay_ms=200),
        ]
        template = _make_template(steps=steps)
        with patch("time.sleep") as mock_sleep:
            executor.run(template)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(0.1)
        mock_sleep.assert_any_call(0.2)
