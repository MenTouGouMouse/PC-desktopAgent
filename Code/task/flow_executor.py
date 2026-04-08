"""任务层：流程执行器。

加载并验证 Flow_Template JSON 文件，按步骤顺序调用 ActionEngine 回放录制的操作序列。
加载时使用 jsonschema 验证 schema，格式不合法时抛出 ValidationError 且不执行任何操作。
回放过程中某步失败时立即停止并返回包含失败步骤信息的 ExecutionReport。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import ValidationError

from execution.action_engine import ActionEngine
from task.flow_schema import FlowTemplate, Step

logger = logging.getLogger(__name__)

# 加载 JSON Schema（相对于本文件所在目录）
_SCHEMA_PATH = Path(__file__).parent / "schema" / "flow_template.schema.json"


def _load_schema() -> dict[str, Any]:
    with _SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@dataclass
class ExecutionReport:
    """回放执行报告。

    Attributes:
        success:        是否全部步骤执行成功。
        failed_step_id: 失败步骤的 step_id；全部成功时为 None。
        reason:         失败原因描述；全部成功时为空字符串。
        completed_steps: 成功完成的步骤 step_id 列表。
    """

    success: bool
    failed_step_id: int | None = None
    reason: str = ""
    completed_steps: list[int] = field(default_factory=list)


class FlowExecutor:
    """流程执行器：加载 Flow_Template 并按步骤顺序回放。"""

    def __init__(self, action_engine: ActionEngine | None = None) -> None:
        """初始化 FlowExecutor。

        Args:
            action_engine: 可选的 ActionEngine 实例；若为 None 则自动创建。
        """
        self._engine = action_engine if action_engine is not None else ActionEngine()
        self._schema = _load_schema()
        logger.info("FlowExecutor 初始化完成")

    def load(self, path: str) -> FlowTemplate:
        """从文件路径加载并验证 Flow_Template JSON。

        使用 jsonschema 验证文件内容是否符合 flow_template.schema.json。
        验证失败时抛出 ValidationError（含验证错误详情），不执行任何操作。

        Args:
            path: Flow_Template JSON 文件路径。

        Returns:
            验证通过的 FlowTemplate 对象。

        Raises:
            ValidationError: JSON 内容不符合 schema 时抛出。
            FileNotFoundError: 文件不存在时抛出。
            json.JSONDecodeError: 文件内容不是合法 JSON 时抛出。
        """
        file_path = Path(path)
        logger.info("FlowExecutor.load: 加载文件 %s", file_path)

        with file_path.open(encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)

        # jsonschema 验证；失败时直接向上传播 ValidationError
        try:
            jsonschema.validate(instance=data, schema=self._schema)
        except ValidationError as exc:
            logger.error(
                "FlowExecutor.load: schema 验证失败 (%s): %s",
                file_path,
                exc.message,
            )
            raise

        template = FlowTemplate.from_dict(data)
        logger.info(
            "FlowExecutor.load: 加载成功，模板='%s'，步骤数=%d",
            template.name,
            len(template.steps),
        )
        return template

    def run(self, template: FlowTemplate) -> ExecutionReport:
        """按 step_id 升序回放 FlowTemplate 中的所有步骤。

        每步之间按 delay_ms 字段等待。某步失败时立即停止并返回失败报告。

        Args:
            template: 已通过 schema 验证的 FlowTemplate 对象。

        Returns:
            ExecutionReport，包含执行结果、失败步骤 ID 和原因。
        """
        sorted_steps: list[Step] = sorted(template.steps, key=lambda s: s.step_id)
        completed: list[int] = []

        logger.info(
            "FlowExecutor.run: 开始回放模板='%s'，共 %d 步",
            template.name,
            len(sorted_steps),
        )

        for step in sorted_steps:
            logger.debug(
                "FlowExecutor.run: 执行步骤 step_id=%d, action_type=%s, params=%s",
                step.step_id,
                step.action_type,
                step.parameters,
            )

            success, reason = self._execute_step(step)

            if not success:
                logger.error(
                    "FlowExecutor.run: 步骤 step_id=%d 执行失败，停止回放。原因: %s",
                    step.step_id,
                    reason,
                )
                return ExecutionReport(
                    success=False,
                    failed_step_id=step.step_id,
                    reason=reason,
                    completed_steps=completed,
                )

            completed.append(step.step_id)
            logger.info("FlowExecutor.run: 步骤 step_id=%d 执行成功", step.step_id)

            # 步骤间延迟
            if step.delay_ms > 0:
                time.sleep(step.delay_ms / 1000.0)

        logger.info("FlowExecutor.run: 回放完成，共执行 %d 步", len(completed))
        return ExecutionReport(success=True, completed_steps=completed)

    def _execute_step(self, step: Step) -> tuple[bool, str]:
        """执行单个步骤，返回 (success, reason)。"""
        try:
            action = step.action_type
            params = step.parameters

            if action == "mouse_click":
                result = self._engine.click(
                    x=int(params["x"]),
                    y=int(params["y"]),
                    click_type=params.get("click_type", "single"),
                )
                if not result:
                    return False, f"click 返回 False，坐标=({params['x']}, {params['y']})"

            elif action == "mouse_move":
                result = self._engine.move_to(
                    x=int(params["x"]),
                    y=int(params["y"]),
                )
                if not result:
                    return False, f"move_to 返回 False，坐标=({params['x']}, {params['y']})"

            elif action == "key_press":
                result = self._engine.key_press(key=params["key"])
                if not result:
                    return False, f"key_press 返回 False，key='{params['key']}'"

            elif action == "type_text":
                result = self._engine.type_text(text=params["text"])
                if not result:
                    return False, f"type_text 返回 False，text='{params['text']}'"

            else:
                return False, f"未知的 action_type: {action!r}"

            return True, ""

        except Exception as exc:
            return False, str(exc)
