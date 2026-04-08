"""Property-based tests for FlowTemplate JSON round-trip serialization.

# Feature: cv-desktop-automation-agent, Property 14: FlowTemplate 序列化往返属性
"""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from task.flow_schema import ActionType, FlowTemplate, Step

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_ACTION_TYPES: list[ActionType] = ["mouse_click", "mouse_move", "key_press", "type_text"]

_action_type_st: st.SearchStrategy[ActionType] = st.sampled_from(_ACTION_TYPES)


def _parameters_st(action_type: ActionType) -> st.SearchStrategy[dict]:
    """Return a strategy for valid parameters given an action_type."""
    if action_type in ("mouse_click", "mouse_move"):
        return st.fixed_dictionaries({"x": st.integers(-9999, 9999), "y": st.integers(-9999, 9999)})
    if action_type == "key_press":
        return st.fixed_dictionaries({"key": st.text(min_size=1, max_size=20)})
    # type_text
    return st.fixed_dictionaries({"text": st.text(max_size=200)})


@st.composite
def step_strategy(draw: st.DrawFn) -> Step:
    """Generate a valid Step with action-type-consistent parameters."""
    action_type: ActionType = draw(_action_type_st)
    return Step(
        step_id=draw(st.integers(min_value=0, max_value=10_000)),
        action_type=action_type,
        parameters=draw(_parameters_st(action_type)),
        delay_ms=draw(st.integers(min_value=0, max_value=60_000)),
    )


@st.composite
def flow_template_strategy(draw: st.DrawFn) -> FlowTemplate:
    """Generate a valid FlowTemplate with arbitrary fields and steps."""
    return FlowTemplate(
        version=draw(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Pc")),
            )
        ),
        name=draw(st.text(min_size=1, max_size=50)),
        created_at=draw(st.text(min_size=1, max_size=30)),
        steps=draw(st.lists(step_strategy(), min_size=0, max_size=20)),
    )


# ---------------------------------------------------------------------------
# Property 14: FlowTemplate 序列化往返属性
# Validates: Requirements 10.6
# ---------------------------------------------------------------------------


# Feature: cv-desktop-automation-agent, Property 14: FlowTemplate 序列化往返属性
@settings(max_examples=100)
@given(flow_template_strategy())
def test_flow_template_json_round_trip(template: FlowTemplate) -> None:
    """**Validates: Requirements 10.6**

    For any valid FlowTemplate, serializing to JSON and deserializing back
    must produce a structurally equivalent object with identical field values.

    Asserts: FlowTemplate.from_dict(json.loads(json.dumps(template.to_dict()))) == template
    """
    json_str = json.dumps(template.to_dict())
    restored = FlowTemplate.from_dict(json.loads(json_str))
    assert restored == template
