"""Property-based tests for QueueManager message round-trip.

# Feature: cv-desktop-automation-agent, Property 18: 消息格式往返属性
"""

from __future__ import annotations

from multiprocessing import Queue

from hypothesis import given, settings
from hypothesis import strategies as st

from ui.queue_manager import CommandMessage, QueueManager, StatusMessage

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_CMD_TYPE_ST = st.sampled_from(["execute", "record", "stop"])
_STATUS_ST = st.sampled_from(["running", "success", "error", "timeout"])

# Payload values: keep JSON-serialisable primitives so pickling across
# multiprocessing.Queue is always safe.
_primitive_st = st.one_of(
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.text(max_size=50),
    st.none(),
)

_payload_st: st.SearchStrategy[dict] = st.dictionaries(
    keys=st.text(min_size=1, max_size=20),
    values=_primitive_st,
    max_size=8,
)


# ---------------------------------------------------------------------------
# Property 18: 消息格式往返属性
# Validates: Requirements 12.2, 12.3, 12.4
# ---------------------------------------------------------------------------


# Feature: cv-desktop-automation-agent, Property 18: 消息格式往返属性
@settings(max_examples=100)
@given(msg_type=_CMD_TYPE_ST, payload=_payload_st)
def test_command_message_queue_round_trip(msg_type: str, payload: dict) -> None:
    """**Validates: Requirements 12.2, 12.4**

    For any CommandMessage placed into a multiprocessing.Queue, the retrieved
    message must have identical message_type and payload fields.
    """
    q: Queue[CommandMessage] = Queue()
    original = CommandMessage(message_type=msg_type, payload=payload)  # type: ignore[arg-type]
    q.put(original)
    restored: CommandMessage = q.get(timeout=5.0)

    assert restored.message_type == original.message_type
    assert restored.payload == original.payload


# Feature: cv-desktop-automation-agent, Property 18: 消息格式往返属性
@settings(max_examples=100)
@given(
    status=_STATUS_ST,
    message=st.text(max_size=200),
    timestamp=st.text(max_size=40),
)
def test_status_message_queue_round_trip(status: str, message: str, timestamp: str) -> None:
    """**Validates: Requirements 12.3, 12.4**

    For any StatusMessage placed into a multiprocessing.Queue, the retrieved
    message must have identical status, message, and timestamp fields.
    """
    q: Queue[StatusMessage] = Queue()
    original = StatusMessage(status=status, message=message, timestamp=timestamp)  # type: ignore[arg-type]
    q.put(original)
    restored: StatusMessage = q.get(timeout=5.0)

    assert restored.status == original.status
    assert restored.message == original.message
    assert restored.timestamp == original.timestamp


# Feature: cv-desktop-automation-agent, Property 18: 消息格式往返属性
@settings(max_examples=100)
@given(msg_type=_CMD_TYPE_ST, payload=_payload_st)
def test_send_command_round_trip_via_queue_manager(msg_type: str, payload: dict) -> None:
    """**Validates: Requirements 12.2, 12.4**

    QueueManager.send_command serialises a CommandMessage into cmd_queue;
    reading it back must yield the original message_type and payload.
    """
    qm = QueueManager()
    qm.send_command(msg_type, payload)
    restored: CommandMessage = qm.cmd_queue.get(timeout=5.0)

    assert restored.message_type == msg_type
    assert restored.payload == payload


# Feature: cv-desktop-automation-agent, Property 18: 消息格式往返属性
@settings(max_examples=100)
@given(
    status=_STATUS_ST,
    message=st.text(max_size=200),
    timestamp=st.text(max_size=40),
)
def test_poll_status_round_trip_via_queue_manager(status: str, message: str, timestamp: str) -> None:
    """**Validates: Requirements 12.3, 12.4**

    A StatusMessage placed into QueueManager.status_queue must be returned
    unchanged by poll_status(), preserving all three fields.
    """
    qm = QueueManager()
    original = StatusMessage(status=status, message=message, timestamp=timestamp)  # type: ignore[arg-type]
    qm.status_queue.put(original)
    restored = qm.poll_status(timeout=5.0)

    assert restored.status == original.status
    assert restored.message == original.message
    assert restored.timestamp == original.timestamp
