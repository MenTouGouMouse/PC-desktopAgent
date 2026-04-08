"""Flow_Template dataclass 与序列化方法。

定义 FlowTemplate 和 Step dataclass，对应 task/schema/flow_template.schema.json 中的结构，
并提供 to_dict() / from_dict() 往返序列化支持。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# action_type 枚举值
ActionType = Literal["mouse_click", "mouse_move", "key_press", "type_text"]


@dataclass
class Step:
    """对应 Flow_Template JSON Schema 中的 Step 结构。"""

    step_id: int
    action_type: ActionType
    parameters: dict[str, Any]
    delay_ms: int

    def __post_init__(self) -> None:
        # Defensive copy so callers cannot mutate the stored parameters dict.
        self.parameters = dict(self.parameters)

    def to_dict(self) -> dict[str, Any]:
        """将 Step 序列化为字典。"""
        return {
            "step_id": self.step_id,
            "action_type": self.action_type,
            "parameters": dict(self.parameters),
            "delay_ms": self.delay_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Step:
        """从字典反序列化为 Step 对象。"""
        return cls(
            step_id=data["step_id"],
            action_type=data["action_type"],
            parameters=dict(data.get("parameters", {})),
            delay_ms=data["delay_ms"],
        )


@dataclass
class FlowTemplate:
    """Flow_Template 顶层 dataclass，对应 flow_template.schema.json。

    字段：
        version:    模板版本字符串
        name:       流程名称
        created_at: ISO 8601 格式的创建时间字符串
        steps:      Step 列表，按 step_id 升序排列
    """

    version: str
    name: str
    created_at: str
    steps: list[Step] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """将 FlowTemplate 序列化为字典（可直接 json.dumps）。"""
        result: dict[str, Any] = {
            "version": self.version,
            "name": self.name,
            "created_at": self.created_at,
            "steps": [step.to_dict() for step in self.steps],
        }
        logger.debug("FlowTemplate '%s' serialized to dict (%d steps)", self.name, len(self.steps))
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowTemplate:
        """从字典反序列化为 FlowTemplate 对象。"""
        steps = [Step.from_dict(s) for s in data.get("steps", [])]
        template = cls(
            version=data["version"],
            name=data["name"],
            created_at=data["created_at"],
            steps=steps,
        )
        logger.debug("FlowTemplate '%s' deserialized from dict (%d steps)", template.name, len(steps))
        return template
