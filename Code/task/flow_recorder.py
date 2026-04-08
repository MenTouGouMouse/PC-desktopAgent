"""Flow_Recorder 模块：使用 pynput 监听并录制用户的鼠标和键盘操作，
序列化为符合 Flow_Template JSON Schema 的文件，保存至 recordings/ 目录。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pynput import keyboard, mouse

from task.flow_schema import FlowTemplate, Step

logger = logging.getLogger(__name__)

RECORDINGS_DIR = Path("recordings")
FLOW_TEMPLATE_VERSION = "1.0"


class FlowRecorder:
    """录制用户鼠标和键盘操作，并将其序列化为 FlowTemplate JSON 文件。"""

    def __init__(self) -> None:
        self._name: str = ""
        self._steps: list[Step] = []
        self._last_event_time: float = 0.0
        self._start_time: float = 0.0
        self._mouse_listener: mouse.Listener | None = None
        self._keyboard_listener: keyboard.Listener | None = None
        self._recording: bool = False

    def start(self, name: str) -> None:
        """开始录制用户操作。

        Args:
            name: 录制会话名称，用于生成文件名。
        """
        if self._recording:
            logger.warning("FlowRecorder is already recording; ignoring start() call")
            return

        self._name = name
        self._steps = []
        self._start_time = time.monotonic()
        self._last_event_time = self._start_time
        self._recording = True

        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
        )

        self._mouse_listener.start()
        self._keyboard_listener.start()
        logger.info("FlowRecorder started recording session '%s'", name)

    def stop(self) -> str:
        """停止录制，序列化为 FlowTemplate JSON 并保存，在 2 秒内完成。

        Returns:
            保存的文件路径字符串。

        Raises:
            RuntimeError: 如果当前未在录制状态。
        """
        if not self._recording:
            raise RuntimeError("FlowRecorder is not currently recording")

        self._recording = False

        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None

        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()
            self._keyboard_listener = None

        file_path = self._serialize_and_save()
        logger.info("FlowRecorder stopped; saved to '%s'", file_path)
        return file_path

    # ------------------------------------------------------------------
    # pynput event handlers
    # ------------------------------------------------------------------

    def _on_mouse_move(self, x: int, y: int) -> None:
        """处理鼠标移动事件。"""
        if not self._recording:
            return
        self._append_step(
            action_type="mouse_move",
            parameters={"x": int(x), "y": int(y)},
        )

    def _on_mouse_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        """处理鼠标点击事件（仅记录按下动作）。"""
        if not self._recording or not pressed:
            return
        self._append_step(
            action_type="mouse_click",
            parameters={"x": int(x), "y": int(y)},
        )

    def _on_key_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        """处理键盘按键事件。"""
        if not self._recording or key is None:
            return

        key_str = self._key_to_str(key)
        if key_str is None:
            return

        # Single printable characters are recorded as type_text for readability.
        if len(key_str) == 1:
            self._append_step(action_type="type_text", parameters={"text": key_str})
        else:
            self._append_step(action_type="key_press", parameters={"key": key_str})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key_to_str(self, key: keyboard.Key | keyboard.KeyCode) -> str | None:
        """将 pynput key 对象转换为字符串表示。

        Args:
            key: pynput 键盘事件对象。

        Returns:
            字符串表示，无法转换时返回 None。
        """
        try:
            if isinstance(key, keyboard.KeyCode):
                # Regular character key
                if key.char is not None:
                    return key.char
                # Virtual key with no char representation
                return f"vk:{key.vk}" if key.vk is not None else None
            else:
                # Special key (Key.space, Key.enter, etc.)
                return key.name
        except Exception as exc:  # pragma: no cover
            logger.debug("Could not convert key to string: %s", exc)
            return None

    def _compute_delay_ms(self) -> int:
        """计算距上一个事件的延迟（毫秒）。"""
        now = time.monotonic()
        delay = int((now - self._last_event_time) * 1000)
        self._last_event_time = now
        return max(0, delay)

    def _append_step(self, action_type: str, parameters: dict[str, Any]) -> None:
        """追加一个录制步骤。"""
        delay_ms = self._compute_delay_ms()
        step = Step(
            step_id=len(self._steps) + 1,
            action_type=action_type,  # type: ignore[arg-type]
            parameters=parameters,
            delay_ms=delay_ms,
        )
        self._steps.append(step)
        logger.debug("Recorded step %d: %s %s (delay=%dms)", step.step_id, action_type, parameters, delay_ms)

    def _serialize_and_save(self) -> str:
        """将录制的步骤序列化为 FlowTemplate JSON 并保存到 recordings/ 目录。

        Returns:
            保存的文件路径字符串。
        """
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{self._name}_{timestamp}.json"
        file_path = RECORDINGS_DIR / filename

        template = FlowTemplate(
            version=FLOW_TEMPLATE_VERSION,
            name=self._name,
            created_at=datetime.now(tz=timezone.utc).isoformat(),
            steps=list(self._steps),
        )

        data = template.to_dict()
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

        logger.info(
            "FlowTemplate '%s' saved to '%s' (%d steps)",
            self._name,
            file_path,
            len(self._steps),
        )
        return str(file_path)
