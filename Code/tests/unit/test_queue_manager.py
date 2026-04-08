"""ui/queue_manager.py 的单元测试。

覆盖 CommandMessage、StatusMessage dataclass 及 QueueManager 的核心行为。
"""

from __future__ import annotations

import time
from multiprocessing import Queue
from unittest.mock import patch

import pytest

from ui.queue_manager import CommandMessage, QueueManager, StatusMessage


# ---------------------------------------------------------------------------
# CommandMessage
# ---------------------------------------------------------------------------

class TestCommandMessage:
    def test_fields_stored_correctly(self) -> None:
        msg = CommandMessage(message_type="execute", payload={"task": "open_app"})
        assert msg.message_type == "execute"
        assert msg.payload == {"task": "open_app"}

    def test_all_valid_types(self) -> None:
        for t in ("execute", "record", "stop"):
            msg = CommandMessage(message_type=t, payload={})  # type: ignore[arg-type]
            assert msg.message_type == t


# ---------------------------------------------------------------------------
# StatusMessage
# ---------------------------------------------------------------------------

class TestStatusMessage:
    def test_fields_stored_correctly(self) -> None:
        msg = StatusMessage(status="success", message="done", timestamp="2024-01-01T00:00:00+00:00")
        assert msg.status == "success"
        assert msg.message == "done"
        assert msg.timestamp == "2024-01-01T00:00:00+00:00"

    def test_all_valid_statuses(self) -> None:
        for s in ("running", "success", "error", "timeout"):
            msg = StatusMessage(status=s, message="", timestamp="")  # type: ignore[arg-type]
            assert msg.status == s


# ---------------------------------------------------------------------------
# QueueManager.send_command
# ---------------------------------------------------------------------------

class TestSendCommand:
    def test_send_execute_puts_message_in_queue(self) -> None:
        qm = QueueManager()
        qm.send_command("execute", {"instruction": "click OK"})
        msg: CommandMessage = qm.cmd_queue.get(timeout=2.0)
        assert msg.message_type == "execute"
        assert msg.payload == {"instruction": "click OK"}

    def test_send_record_puts_message_in_queue(self) -> None:
        qm = QueueManager()
        qm.send_command("record", {"name": "flow1"})
        msg: CommandMessage = qm.cmd_queue.get(timeout=1.0)
        assert msg.message_type == "record"

    def test_send_stop_puts_message_in_queue(self) -> None:
        qm = QueueManager()
        qm.send_command("stop", {})
        msg: CommandMessage = qm.cmd_queue.get(timeout=2.0)
        assert msg.message_type == "stop"

    def test_invalid_message_type_raises_value_error(self) -> None:
        qm = QueueManager()
        with pytest.raises(ValueError, match="Invalid message_type"):
            qm.send_command("unknown", {})

    def test_queue_is_empty_before_send(self) -> None:
        qm = QueueManager()
        assert qm.cmd_queue.empty()

    def test_multiple_commands_queued_in_order(self) -> None:
        qm = QueueManager()
        qm.send_command("execute", {"n": 1})
        qm.send_command("stop", {})
        first: CommandMessage = qm.cmd_queue.get(timeout=2.0)
        second: CommandMessage = qm.cmd_queue.get(timeout=2.0)
        assert first.message_type == "execute"
        assert second.message_type == "stop"


# ---------------------------------------------------------------------------
# QueueManager.poll_status
# ---------------------------------------------------------------------------

class TestPollStatus:
    def test_returns_message_when_available(self) -> None:
        qm = QueueManager()
        expected = StatusMessage(status="success", message="ok", timestamp="2024-01-01T00:00:00+00:00")
        qm.status_queue.put(expected)
        result = qm.poll_status(timeout=5.0)
        assert result.status == "success"
        assert result.message == "ok"

    def test_returns_timeout_message_when_queue_empty(self) -> None:
        qm = QueueManager()
        result = qm.poll_status(timeout=0.05)
        assert result.status == "timeout"
        assert "0.05" in result.message or "秒" in result.message

    def test_timeout_message_has_iso_timestamp(self) -> None:
        qm = QueueManager()
        result = qm.poll_status(timeout=0.05)
        # ISO 8601 timestamps contain 'T' and '+'
        assert "T" in result.timestamp

    def test_timeout_message_pushed_to_status_queue(self) -> None:
        """超时后 timeout 消息应被推入 status_queue（供后续消费者读取）。"""
        qm = QueueManager()
        qm.poll_status(timeout=0.05)
        # The timeout message was put back into the queue
        msg: StatusMessage = qm.status_queue.get(timeout=2.0)
        assert msg.status == "timeout"

    def test_running_status_returned_correctly(self) -> None:
        qm = QueueManager()
        qm.status_queue.put(StatusMessage(status="running", message="in progress", timestamp=""))
        result = qm.poll_status(timeout=5.0)
        assert result.status == "running"

    def test_error_status_returned_correctly(self) -> None:
        qm = QueueManager()
        qm.status_queue.put(StatusMessage(status="error", message="crash", timestamp=""))
        result = qm.poll_status(timeout=5.0)
        assert result.status == "error"


# ---------------------------------------------------------------------------
# Property 18: 消息格式往返属性
# ---------------------------------------------------------------------------

class TestMessageRoundTrip:
    """Property 18: CommandMessage / StatusMessage 放入 Queue 再取出，字段值完全等价。

    Validates: Requirements 12.2, 12.3, 12.4
    """

    def test_command_message_round_trip(self) -> None:
        q: Queue[CommandMessage] = Queue()
        original = CommandMessage(message_type="execute", payload={"key": "value", "num": 42})
        q.put(original)
        restored: CommandMessage = q.get(timeout=2.0)
        assert restored.message_type == original.message_type
        assert restored.payload == original.payload

    def test_status_message_round_trip(self) -> None:
        q: Queue[StatusMessage] = Queue()
        original = StatusMessage(status="success", message="完成", timestamp="2024-06-01T12:00:00+00:00")
        q.put(original)
        restored: StatusMessage = q.get(timeout=1.0)
        assert restored.status == original.status
        assert restored.message == original.message
        assert restored.timestamp == original.timestamp

    def test_command_message_with_nested_payload_round_trip(self) -> None:
        q: Queue[CommandMessage] = Queue()
        payload = {"nested": {"a": 1, "b": [1, 2, 3]}, "flag": True}
        original = CommandMessage(message_type="record", payload=payload)
        q.put(original)
        restored: CommandMessage = q.get(timeout=1.0)
        assert restored.payload == payload
