"""队列管理模块：负责 UI 进程与执行进程之间的进程间通信。

通过 multiprocessing.Queue 传递指令消息（CommandMessage）和状态消息（StatusMessage），
实现进程隔离，确保执行进程异常不影响 UI 可用性。
"""

from __future__ import annotations

import logging
import queue
from dataclasses import dataclass
from datetime import datetime, timezone
from multiprocessing import Queue
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class CommandMessage:
    """UI 进程发往执行进程的指令消息。"""

    message_type: Literal["execute", "record", "stop"]
    payload: dict


@dataclass
class StatusMessage:
    """执行进程发往 UI 进程的状态消息。"""

    status: Literal["running", "success", "error", "timeout"]
    message: str
    timestamp: str  # ISO 8601


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(tz=timezone.utc).isoformat()


class QueueManager:
    """管理 UI 进程与执行进程之间的双向消息队列。

    cmd_queue:    UI → 执行进程（指令消息）
    status_queue: 执行进程 → UI（状态消息）
    """

    def __init__(
        self,
        cmd_queue: Queue[CommandMessage] | None = None,
        status_queue: Queue[StatusMessage] | None = None,
    ) -> None:
        self.cmd_queue: Queue[CommandMessage] = cmd_queue if cmd_queue is not None else Queue()
        self.status_queue: Queue[StatusMessage] = status_queue if status_queue is not None else Queue()
        logger.info("QueueManager initialized")

    def send_command(self, msg_type: str, payload: dict) -> None:
        """序列化指令消息并放入指令队列。

        Args:
            msg_type: 指令类型，枚举值：execute / record / stop。
            payload:  指令附带的参数对象。

        Raises:
            ValueError: 当 msg_type 不在允许的枚举值中时。
        """
        allowed: tuple[str, ...] = ("execute", "record", "stop")
        if msg_type not in allowed:
            raise ValueError(f"Invalid message_type '{msg_type}', must be one of {allowed}")

        msg = CommandMessage(message_type=msg_type, payload=payload)  # type: ignore[arg-type]
        self.cmd_queue.put(msg)
        logger.debug("Command sent: type=%s payload=%s", msg_type, payload)

    def poll_status(self, timeout: float = 30.0) -> StatusMessage:
        """从状态队列中取出一条状态消息，超时则推送 timeout 状态消息。

        Args:
            timeout: 等待超时秒数，默认 30.0 秒（对应 Requirement 12.5）。

        Returns:
            StatusMessage：执行进程推送的状态，或超时时生成的 timeout 消息。
        """
        try:
            msg: StatusMessage = self.status_queue.get(timeout=timeout)
            logger.debug("Status received: status=%s message=%s", msg.status, msg.message)
            return msg
        except queue.Empty:
            timeout_msg = StatusMessage(
                status="timeout",
                message=f"执行进程在 {timeout} 秒内未返回状态消息",
                timestamp=_now_iso(),
            )
            logger.warning("poll_status timed out after %.1f seconds, pushing timeout message", timeout)
            self.status_queue.put(timeout_msg)
            return timeout_msg
