"""属性测试：FlowExecutor 核心行为属性验证。

覆盖属性：
- Property 15: 无效 JSON 加载时抛出 ValidationError 且不执行操作
- Property 16: 回放按步骤顺序执行并遵守延迟
- Property 17: 回放失败时停止并返回失败报告

# Feature: cv-desktop-automation-agent
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import ValidationError

from task.flow_executor import ExecutionReport, FlowExecutor
from task.flow_schema import ActionType, FlowTemplate, Step

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

_ACTION_TYPES: list[ActionType] = ["mouse_click", "mouse_move", "key_press", "type_text"]
_action_type_st: st.SearchStrategy[ActionType] = st.sampled_from(_ACTION_TYPES)


def _params_for(action_type: ActionType) -> st.SearchStrategy[dict[str, Any]]:
    if action_type in ("mouse_click", "mouse_move"):
        return st.fixed_dictionaries(
            {"x": st.integers(0, 1919), "y": st.integers(0, 1079)}
        )
    if action_type == "key_press":
        return st.fixed_dictionaries({"key": st.sampled_from(["enter", "tab", "escape", "space"])})
    return st.fixed_dictionaries({"text": st.text(min_size=1, max_size=50)})


@st.composite
def _step_st(draw: st.DrawFn, step_id: int | None = None) -> Step:
    action_type: ActionType = draw(_action_type_st)
    return Step(
        step_id=draw(st.integers(1, 1000)) if step_id is None else step_id,
        action_type=action_type,
        parameters=draw(_params_for(action_type)),
        delay_ms=draw(st.integers(0, 500)),
    )


@st.composite
def _valid_template_st(draw: st.DrawFn, min_steps: int = 1, max_steps: int = 10) -> FlowTemplate:
    """Generate a valid FlowTemplate with unique sequential step_ids."""
    n = draw(st.integers(min_steps, max_steps))
    steps = []
    for i in range(1, n + 1):
        action_type: ActionType = draw(_action_type_st)
        steps.append(Step(
            step_id=i,
            action_type=action_type,
            parameters=draw(_params_for(action_type)),
            delay_ms=draw(st.integers(0, 200)),
        ))
    return FlowTemplate(
        version="1.0",
        name=draw(st.text(min_size=1, max_size=30)),
        created_at="2024-01-01T00:00:00Z",
        steps=steps,
    )


def _make_executor(engine: MagicMock | None = None) -> FlowExecutor:
    if engine is None:
        engine = MagicMock()
        engine.click.return_value = True
        engine.move_to.return_value = True
        engine.key_press.return_value = True
        engine.type_text.return_value = True
    return FlowExecutor(action_engine=engine)


def _write_json(tmp_dir: str, data: Any, filename: str = "flow.json") -> str:
    path = Path(tmp_dir) / filename
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Property 15: 无效 JSON 加载时抛出 ValidationError 且不执行操作
# Feature: cv-desktop-automation-agent, Property 15: 无效 JSON 加载时抛出 ValidationError 且不执行操作
# Validates: Requirements 9.2
# ---------------------------------------------------------------------------

# Strategies for generating invalid JSON structures (valid JSON, but wrong schema)
_invalid_template_st = st.one_of(
    # Missing required top-level fields
    st.fixed_dictionaries({"version": st.text(min_size=1), "name": st.text(min_size=1)}),
    st.fixed_dictionaries({"name": st.text(min_size=1), "created_at": st.just("2024-01-01T00:00:00Z")}),
    st.fixed_dictionaries({"version": st.text(min_size=1), "steps": st.just([])}),
    # Wrong type for 'steps'
    st.fixed_dictionaries({
        "version": st.text(min_size=1),
        "name": st.text(min_size=1),
        "created_at": st.just("2024-01-01T00:00:00Z"),
        "steps": st.one_of(st.just(None), st.just("not_a_list"), st.integers()),
    }),
    # Steps with invalid action_type
    st.fixed_dictionaries({
        "version": st.text(min_size=1),
        "name": st.text(min_size=1),
        "created_at": st.just("2024-01-01T00:00:00Z"),
        "steps": st.just([{
            "step_id": 1,
            "action_type": "invalid_action",
            "parameters": {},
            "delay_ms": 0,
        }]),
    }),
    # Steps missing required fields
    st.fixed_dictionaries({
        "version": st.text(min_size=1),
        "name": st.text(min_size=1),
        "created_at": st.just("2024-01-01T00:00:00Z"),
        "steps": st.just([{"step_id": 1, "action_type": "mouse_click"}]),  # missing parameters, delay_ms
    }),
    # Negative delay_ms
    st.fixed_dictionaries({
        "version": st.text(min_size=1),
        "name": st.text(min_size=1),
        "created_at": st.just("2024-01-01T00:00:00Z"),
        "steps": st.just([{
            "step_id": 1,
            "action_type": "mouse_click",
            "parameters": {"x": 10, "y": 20},
            "delay_ms": -1,
        }]),
    }),
)


class TestProperty15InvalidJsonRaisesValidationError:
    """无效 JSON 加载时抛出 ValidationError 且不执行操作。"""

    # Feature: cv-desktop-automation-agent, Property 15: 无效 JSON 加载时抛出 ValidationError 且不执行操作
    @settings(max_examples=100)
    @given(invalid_data=_invalid_template_st)
    def test_load_invalid_schema_raises_validation_error(self, invalid_data: Any) -> None:
        """**Validates: Requirements 9.2**

        For any JSON object that does not conform to flow_template.schema.json,
        FlowExecutor.load() must raise ValidationError and must not execute any action.
        """
        # Feature: cv-desktop-automation-agent, Property 15: 无效 JSON 加载时抛出 ValidationError 且不执行操作
        engine = MagicMock()
        executor = _make_executor(engine)

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, invalid_data)
            with pytest.raises(ValidationError):
                executor.load(path)

        # No action engine methods should have been called
        engine.click.assert_not_called()
        engine.move_to.assert_not_called()
        engine.key_press.assert_not_called()
        engine.type_text.assert_not_called()

    # Feature: cv-desktop-automation-agent, Property 15: 无效 JSON 加载时抛出 ValidationError 且不执行操作
    @settings(max_examples=100)
    @given(invalid_data=_invalid_template_st)
    def test_load_invalid_schema_validation_error_contains_details(self, invalid_data: Any) -> None:
        """**Validates: Requirements 9.2**

        The raised ValidationError must contain a non-empty message describing
        the validation failure.
        """
        # Feature: cv-desktop-automation-agent, Property 15: 无效 JSON 加载时抛出 ValidationError 且不执行操作
        executor = _make_executor()

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(tmp, invalid_data)
            try:
                executor.load(path)
                pytest.fail("Expected ValidationError was not raised")
            except ValidationError as exc:
                assert exc.message, "ValidationError.message must not be empty"


# ---------------------------------------------------------------------------
# Property 16: 回放按步骤顺序执行并遵守延迟
# Feature: cv-desktop-automation-agent, Property 16: 回放按步骤顺序执行并遵守延迟
# Validates: Requirements 9.3, 9.4
# ---------------------------------------------------------------------------

class TestProperty16ExecutionOrderAndDelay:
    """回放按步骤顺序执行并遵守延迟。"""

    # Feature: cv-desktop-automation-agent, Property 16: 回放按步骤顺序执行并遵守延迟
    @settings(max_examples=100)
    @given(template=_valid_template_st(min_steps=2, max_steps=8))
    def test_steps_executed_in_step_id_order(self, template: FlowTemplate) -> None:
        """**Validates: Requirements 9.3**

        For any FlowTemplate with multiple steps, run() must execute them in
        ascending step_id order regardless of the order they appear in the list.
        """
        # Feature: cv-desktop-automation-agent, Property 16: 回放按步骤顺序执行并遵守延迟
        execution_order: list[int] = []
        engine = MagicMock()

        def record_click(x: int, y: int, click_type: str = "single") -> bool:
            # Find which step_id has these coords
            for step in template.steps:
                if step.action_type in ("mouse_click", "mouse_move"):
                    if step.parameters.get("x") == x and step.parameters.get("y") == y:
                        execution_order.append(step.step_id)
                        break
            return True

        def record_move(x: int, y: int) -> bool:
            for step in template.steps:
                if step.action_type == "mouse_move":
                    if step.parameters.get("x") == x and step.parameters.get("y") == y:
                        execution_order.append(step.step_id)
                        break
            return True

        def record_key(key: str) -> bool:
            for step in template.steps:
                if step.action_type == "key_press" and step.parameters.get("key") == key:
                    execution_order.append(step.step_id)
                    break
            return True

        def record_text(text: str) -> bool:
            for step in template.steps:
                if step.action_type == "type_text" and step.parameters.get("text") == text:
                    execution_order.append(step.step_id)
                    break
            return True

        engine.click.side_effect = record_click
        engine.move_to.side_effect = record_move
        engine.key_press.side_effect = record_key
        engine.type_text.side_effect = record_text

        executor = _make_executor(engine)

        # Shuffle the steps to verify sorting happens inside run()
        import random
        shuffled_steps = list(template.steps)
        random.shuffle(shuffled_steps)
        shuffled_template = FlowTemplate(
            version=template.version,
            name=template.name,
            created_at=template.created_at,
            steps=shuffled_steps,
        )

        with patch("time.sleep"):
            report = executor.run(shuffled_template)

        assert report.success is True
        # completed_steps must be in ascending step_id order
        assert report.completed_steps == sorted(report.completed_steps)
        assert report.completed_steps == [s.step_id for s in sorted(template.steps, key=lambda s: s.step_id)]

    # Feature: cv-desktop-automation-agent, Property 16: 回放按步骤顺序执行并遵守延迟
    @settings(max_examples=100)
    @given(template=_valid_template_st(min_steps=1, max_steps=8))
    def test_delay_respected_for_each_step(self, template: FlowTemplate) -> None:
        """**Validates: Requirements 9.4**

        For each step with delay_ms > 0, time.sleep must be called with
        delay_ms / 1000.0 seconds. Steps with delay_ms == 0 must not trigger sleep.
        """
        # Feature: cv-desktop-automation-agent, Property 16: 回放按步骤顺序执行并遵守延迟
        engine = MagicMock()
        engine.click.return_value = True
        engine.move_to.return_value = True
        engine.key_press.return_value = True
        engine.type_text.return_value = True
        executor = _make_executor(engine)

        sorted_steps = sorted(template.steps, key=lambda s: s.step_id)
        expected_sleep_calls = [
            call(s.delay_ms / 1000.0)
            for s in sorted_steps
            if s.delay_ms > 0
        ]

        with patch("time.sleep") as mock_sleep:
            report = executor.run(template)

        assert report.success is True
        assert mock_sleep.call_count == len(expected_sleep_calls)
        if expected_sleep_calls:
            mock_sleep.assert_has_calls(expected_sleep_calls, any_order=False)

    # Feature: cv-desktop-automation-agent, Property 16: 回放按步骤顺序执行并遵守延迟
    @settings(max_examples=100)
    @given(template=_valid_template_st(min_steps=1, max_steps=8))
    def test_all_steps_appear_in_completed_steps_on_success(self, template: FlowTemplate) -> None:
        """**Validates: Requirements 9.3**

        On full success, completed_steps must contain every step_id in the template.
        """
        # Feature: cv-desktop-automation-agent, Property 16: 回放按步骤顺序执行并遵守延迟
        engine = MagicMock()
        engine.click.return_value = True
        engine.move_to.return_value = True
        engine.key_press.return_value = True
        engine.type_text.return_value = True
        executor = _make_executor(engine)

        with patch("time.sleep"):
            report = executor.run(template)

        assert report.success is True
        expected_ids = sorted(s.step_id for s in template.steps)
        assert report.completed_steps == expected_ids


# ---------------------------------------------------------------------------
# Property 17: 回放失败时停止并返回失败报告
# Feature: cv-desktop-automation-agent, Property 17: 回放失败时停止并返回失败报告
# Validates: Requirements 9.5
# ---------------------------------------------------------------------------

@st.composite
def _template_with_failing_step_st(draw: st.DrawFn) -> tuple[FlowTemplate, int]:
    """Generate a FlowTemplate and the step_id of the step that will fail.

    Returns (template, failing_step_id).
    """
    n = draw(st.integers(2, 8))
    steps = []
    for i in range(1, n + 1):
        action_type: ActionType = draw(_action_type_st)
        steps.append(Step(
            step_id=i,
            action_type=action_type,
            parameters=draw(_params_for(action_type)),
            delay_ms=0,
        ))
    # Pick a step to fail (any step from 1..n)
    failing_step_id = draw(st.integers(1, n))
    template = FlowTemplate(
        version="1.0",
        name=draw(st.text(min_size=1, max_size=20)),
        created_at="2024-01-01T00:00:00Z",
        steps=steps,
    )
    return template, failing_step_id


class TestProperty17FailureStopsAndReturnsReport:
    """回放失败时停止并返回失败报告。"""

    # Feature: cv-desktop-automation-agent, Property 17: 回放失败时停止并返回失败报告
    @settings(max_examples=100)
    @given(data=_template_with_failing_step_st())
    def test_run_stops_at_failing_step(self, data: tuple[FlowTemplate, int]) -> None:
        """**Validates: Requirements 9.5**

        When a step fails (engine returns False), run() must stop immediately
        and not execute any subsequent steps.
        """
        # Feature: cv-desktop-automation-agent, Property 17: 回放失败时停止并返回失败报告
        template, failing_step_id = data
        sorted_steps = sorted(template.steps, key=lambda s: s.step_id)
        executed_step_ids: list[int] = []

        engine = MagicMock()

        def make_side_effect(step: Step) -> Any:
            def side_effect(*args: Any, **kwargs: Any) -> bool:
                executed_step_ids.append(step.step_id)
                return step.step_id != failing_step_id
            return side_effect

        for step in sorted_steps:
            if step.action_type == "mouse_click":
                engine.click.side_effect = make_side_effect(step)
            elif step.action_type == "mouse_move":
                engine.move_to.side_effect = make_side_effect(step)
            elif step.action_type == "key_press":
                engine.key_press.side_effect = make_side_effect(step)
            elif step.action_type == "type_text":
                engine.type_text.side_effect = make_side_effect(step)

        # Use a unified side effect that tracks by step order
        call_counter = [0]

        def unified_side_effect(*args: Any, **kwargs: Any) -> bool:
            idx = call_counter[0]
            call_counter[0] += 1
            current_step = sorted_steps[idx]
            executed_step_ids.append(current_step.step_id)
            return current_step.step_id != failing_step_id

        engine.click.side_effect = unified_side_effect
        engine.move_to.side_effect = unified_side_effect
        engine.key_press.side_effect = unified_side_effect
        engine.type_text.side_effect = unified_side_effect

        executor = _make_executor(engine)

        with patch("time.sleep"):
            report = executor.run(template)

        assert report.success is False
        assert report.failed_step_id == failing_step_id

        # No step after the failing step should have been executed
        for step_id in executed_step_ids:
            assert step_id <= failing_step_id, (
                f"Step {step_id} was executed after failing step {failing_step_id}"
            )

    # Feature: cv-desktop-automation-agent, Property 17: 回放失败时停止并返回失败报告
    @settings(max_examples=100)
    @given(data=_template_with_failing_step_st())
    def test_run_failure_report_contains_failed_step_id(self, data: tuple[FlowTemplate, int]) -> None:
        """**Validates: Requirements 9.5**

        The ExecutionReport returned on failure must have success=False and
        failed_step_id equal to the step that failed.
        """
        # Feature: cv-desktop-automation-agent, Property 17: 回放失败时停止并返回失败报告
        template, failing_step_id = data
        sorted_steps = sorted(template.steps, key=lambda s: s.step_id)
        call_counter = [0]

        engine = MagicMock()

        def unified_side_effect(*args: Any, **kwargs: Any) -> bool:
            idx = call_counter[0]
            call_counter[0] += 1
            current_step = sorted_steps[idx]
            return current_step.step_id != failing_step_id

        engine.click.side_effect = unified_side_effect
        engine.move_to.side_effect = unified_side_effect
        engine.key_press.side_effect = unified_side_effect
        engine.type_text.side_effect = unified_side_effect

        executor = _make_executor(engine)

        with patch("time.sleep"):
            report = executor.run(template)

        assert report.success is False
        assert report.failed_step_id == failing_step_id
        assert isinstance(report.reason, str) and len(report.reason) > 0

    # Feature: cv-desktop-automation-agent, Property 17: 回放失败时停止并返回失败报告
    @settings(max_examples=100)
    @given(data=_template_with_failing_step_st())
    def test_run_completed_steps_before_failure_are_recorded(self, data: tuple[FlowTemplate, int]) -> None:
        """**Validates: Requirements 9.5**

        completed_steps in the failure report must contain exactly the step_ids
        of steps that succeeded before the failing step.
        """
        # Feature: cv-desktop-automation-agent, Property 17: 回放失败时停止并返回失败报告
        template, failing_step_id = data
        sorted_steps = sorted(template.steps, key=lambda s: s.step_id)
        call_counter = [0]

        engine = MagicMock()

        def unified_side_effect(*args: Any, **kwargs: Any) -> bool:
            idx = call_counter[0]
            call_counter[0] += 1
            current_step = sorted_steps[idx]
            return current_step.step_id != failing_step_id

        engine.click.side_effect = unified_side_effect
        engine.move_to.side_effect = unified_side_effect
        engine.key_press.side_effect = unified_side_effect
        engine.type_text.side_effect = unified_side_effect

        executor = _make_executor(engine)

        with patch("time.sleep"):
            report = executor.run(template)

        expected_completed = [s.step_id for s in sorted_steps if s.step_id < failing_step_id]
        assert report.completed_steps == expected_completed
