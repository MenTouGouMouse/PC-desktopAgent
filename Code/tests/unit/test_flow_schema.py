"""Unit tests for task/flow_schema.py — FlowTemplate and Step dataclasses."""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from task.flow_schema import ActionType, FlowTemplate, Step

# ---------------------------------------------------------------------------
# Helpers / strategies
# ---------------------------------------------------------------------------

ACTION_TYPES: list[ActionType] = ["mouse_click", "mouse_move", "key_press", "type_text"]


def _params_for(action_type: ActionType) -> dict:
    if action_type in ("mouse_click", "mouse_move"):
        return {"x": 100, "y": 200}
    if action_type == "key_press":
        return {"key": "enter"}
    return {"text": "hello"}


def _make_step(step_id: int = 1, action_type: ActionType = "mouse_click") -> Step:
    return Step(
        step_id=step_id,
        action_type=action_type,
        parameters=_params_for(action_type),
        delay_ms=100,
    )


def _make_template(name: str = "test_flow", steps: list[Step] | None = None) -> FlowTemplate:
    return FlowTemplate(
        version="1.0",
        name=name,
        created_at="2024-01-01T00:00:00Z",
        steps=steps or [_make_step()],
    )


# ---------------------------------------------------------------------------
# Step unit tests
# ---------------------------------------------------------------------------


class TestStep:
    def test_to_dict_contains_required_fields(self) -> None:
        step = _make_step(step_id=3, action_type="key_press")
        d = step.to_dict()
        assert d["step_id"] == 3
        assert d["action_type"] == "key_press"
        assert d["parameters"] == {"key": "enter"}
        assert d["delay_ms"] == 100

    def test_from_dict_round_trip(self) -> None:
        step = _make_step(step_id=5, action_type="type_text")
        restored = Step.from_dict(step.to_dict())
        assert restored == step

    def test_parameters_are_copied(self) -> None:
        """Mutating original parameters dict must not affect the Step."""
        params = {"x": 10, "y": 20}
        step = Step(step_id=1, action_type="mouse_click", parameters=params, delay_ms=0)
        params["x"] = 999
        assert step.parameters["x"] == 10

    @pytest.mark.parametrize("action_type", ACTION_TYPES)
    def test_all_action_types_serialize(self, action_type: ActionType) -> None:
        step = _make_step(action_type=action_type)
        d = step.to_dict()
        assert d["action_type"] == action_type


# ---------------------------------------------------------------------------
# FlowTemplate unit tests
# ---------------------------------------------------------------------------


class TestFlowTemplate:
    def test_to_dict_top_level_fields(self) -> None:
        tmpl = _make_template()
        d = tmpl.to_dict()
        assert d["version"] == "1.0"
        assert d["name"] == "test_flow"
        assert d["created_at"] == "2024-01-01T00:00:00Z"
        assert isinstance(d["steps"], list)

    def test_from_dict_round_trip(self) -> None:
        tmpl = _make_template(steps=[_make_step(1, "mouse_click"), _make_step(2, "key_press")])
        restored = FlowTemplate.from_dict(tmpl.to_dict())
        assert restored == tmpl

    def test_empty_steps(self) -> None:
        tmpl = FlowTemplate(version="1.0", name="empty", created_at="2024-01-01T00:00:00Z", steps=[])
        d = tmpl.to_dict()
        assert d["steps"] == []
        restored = FlowTemplate.from_dict(d)
        assert restored == tmpl

    def test_json_round_trip(self) -> None:
        """Serialize → json.dumps → json.loads → from_dict must produce equal object."""
        tmpl = _make_template(steps=[_make_step(1, "type_text"), _make_step(2, "mouse_move")])
        json_str = json.dumps(tmpl.to_dict())
        restored = FlowTemplate.from_dict(json.loads(json_str))
        assert restored == tmpl

    def test_multiple_steps_preserved_in_order(self) -> None:
        steps = [_make_step(i, ACTION_TYPES[i % len(ACTION_TYPES)]) for i in range(1, 5)]
        tmpl = _make_template(steps=steps)
        restored = FlowTemplate.from_dict(tmpl.to_dict())
        assert [s.step_id for s in restored.steps] == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Property-based tests — Property 14: FlowTemplate 序列化往返属性
# Validates: Requirements 10.6
# ---------------------------------------------------------------------------

# Hypothesis strategies

_action_type_st = st.sampled_from(ACTION_TYPES)


def _parameters_st(action_type: str) -> st.SearchStrategy[dict]:
    if action_type in ("mouse_click", "mouse_move"):
        return st.fixed_dictionaries({"x": st.integers(-9999, 9999), "y": st.integers(-9999, 9999)})
    if action_type == "key_press":
        return st.fixed_dictionaries({"key": st.text(min_size=1, max_size=20)})
    return st.fixed_dictionaries({"text": st.text(max_size=200)})


@st.composite
def step_strategy(draw: st.DrawFn) -> Step:
    action_type: ActionType = draw(_action_type_st)
    return Step(
        step_id=draw(st.integers(min_value=0, max_value=10_000)),
        action_type=action_type,
        parameters=draw(_parameters_st(action_type)),
        delay_ms=draw(st.integers(min_value=0, max_value=60_000)),
    )


@st.composite
def flow_template_strategy(draw: st.DrawFn) -> FlowTemplate:
    return FlowTemplate(
        version=draw(st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Pc")))),
        name=draw(st.text(min_size=1, max_size=50)),
        created_at=draw(st.text(min_size=1, max_size=30)),
        steps=draw(st.lists(step_strategy(), min_size=0, max_size=20)),
    )


# Feature: cv-desktop-automation-agent, Property 14: FlowTemplate 序列化往返属性
@settings(max_examples=100)
@given(flow_template_strategy())
def test_flow_template_round_trip_property(template: FlowTemplate) -> None:
    """**Validates: Requirements 10.6**

    For any valid FlowTemplate, serializing to dict then deserializing must
    produce an object equal to the original.
    """
    json_str = json.dumps(template.to_dict())
    restored = FlowTemplate.from_dict(json.loads(json_str))
    assert restored == template
