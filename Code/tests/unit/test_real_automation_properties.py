"""
属性测试：real-automation-integration 规范的正确性属性验证。

使用 Hypothesis 对 run_file_organizer 进行属性测试。
"""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from automation.file_organizer import run_file_organizer


# ---------------------------------------------------------------------------
# Property 1: 文件过滤器正确筛选文件
# ---------------------------------------------------------------------------

@given(
    filenames=st.lists(
        st.from_regex(r"[a-z]{1,8}\.(jpg|png|pdf|mp4|txt|py)", fullmatch=True),
        min_size=1,
        max_size=20,
    ),
    filters=st.lists(
        st.sampled_from([".jpg", ".png", ".pdf", ".mp4", ".txt", ".py"]),
        min_size=1,
        max_size=4,
    ).map(list),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_file_filter_only_processes_matching_extensions(filenames, filters):
    """Property 1: 文件过滤器正确筛选文件 — Validates: Requirements 1.2"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        for name in filenames:
            (source / name).write_text("data")

        processed_files: list[str] = []

        def callback(step: str, percent: int) -> None:
            # Extract filename from "移动 {name} → {category}/" pattern
            if step.startswith("移动 ") and " → " in step:
                fname = step[len("移动 "):step.index(" → ")]
                processed_files.append(fname)

        stop_event = threading.Event()
        run_file_organizer(source, target, callback, stop_event, file_filters=filters)

        # Every processed file must have an extension in the filter list
        for fname in processed_files:
            ext = Path(fname).suffix.lower()
            assert ext in filters, f"Processed file {fname!r} has ext {ext!r} not in filters {filters}"


# ---------------------------------------------------------------------------
# Property 2: 进度回调百分比始终在 [0, 100] 范围内
# ---------------------------------------------------------------------------

@given(
    filenames=st.lists(
        st.from_regex(r"[a-z]{1,8}\.(jpg|png|pdf|mp4|txt|py)", fullmatch=True),
        min_size=1,
        max_size=30,
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_progress_percent_always_in_range(filenames):
    """Property 2: 进度回调百分比始终在 [0, 100] 范围内 — Validates: Requirements 1.3"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        for name in filenames:
            (source / name).write_text("data")

        percents: list[int] = []

        def callback(step: str, percent: int) -> None:
            percents.append(percent)

        stop_event = threading.Event()
        run_file_organizer(source, target, callback, stop_event)

        assert len(percents) > 0, "Callback should have been called at least once"
        for p in percents:
            assert 0 <= p <= 100, f"percent {p} is out of [0, 100] range"


# ---------------------------------------------------------------------------
# Property 3: 停止信号终止文件处理
# ---------------------------------------------------------------------------

@given(
    filenames=st.lists(
        st.from_regex(r"[a-z]{1,8}\.(jpg|png|pdf|mp4|txt|py)", fullmatch=True),
        min_size=2,
        max_size=20,
    ).filter(lambda x: len(set(x)) == len(x)),  # unique filenames
    stop_at=st.integers(min_value=0, max_value=10),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_stop_event_terminates_processing(filenames, stop_at):
    """Property 3: 停止信号终止文件处理 — Validates: Requirements 1.4"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        for name in filenames:
            (source / name).write_text("data")

        call_count = 0
        stop_event = threading.Event()

        def callback(step: str, percent: int) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= stop_at:
                stop_event.set()

        run_file_organizer(source, target, callback, stop_event)

        # Actual processed files should be <= stop_at + 1 (the one that triggered stop)
        total = len(filenames)
        if stop_at < total:
            assert call_count <= stop_at + 1, (
                f"Expected at most {stop_at + 1} callbacks, got {call_count}"
            )


# ---------------------------------------------------------------------------
# Property 4: 最终回调百分比为 100
# ---------------------------------------------------------------------------

@given(
    filenames=st.lists(
        st.from_regex(r"[a-z]{1,8}\.(jpg|png|pdf|mp4|txt|py)", fullmatch=True),
        min_size=1,
        max_size=20,
    ).filter(lambda x: len(set(x)) == len(x)),  # unique filenames
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_final_callback_percent_is_100(filenames):
    """Property 4: 最终回调百分比为 100 — Validates: Requirements 1.7"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        for name in filenames:
            (source / name).write_text("data")

        last_percent: list[int] = []

        def callback(step: str, percent: int) -> None:
            last_percent.clear()
            last_percent.append(percent)

        stop_event = threading.Event()
        run_file_organizer(source, target, callback, stop_event)

        assert len(last_percent) > 0, "Callback should have been called"
        assert last_percent[-1] == 100, f"Final percent should be 100, got {last_percent[-1]}"


# ---------------------------------------------------------------------------
# Property 5: 安装步骤回调百分比始终在 [0, 100] 范围内
# ---------------------------------------------------------------------------

@given(
    step_count=st.integers(min_value=1, max_value=8),
)
@settings(max_examples=100)
def test_installer_progress_percent_always_in_range(step_count):
    """Property 5: 安装步骤回调百分比始终在 [0, 100] 范围内 — Validates: Requirements 2.4"""
    import tempfile
    from unittest.mock import MagicMock, patch
    from automation.software_installer import InstallStep, run_software_installer
    from perception.element_locator import ElementResult

    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "installer.exe"
        pkg.write_bytes(b"fake")

        # Build dynamic steps
        steps = [InstallStep(f"按钮{i}", f"步骤{i}") for i in range(step_count)]

        percents: list[int] = []

        def callback(step: str, percent: int) -> None:
            percents.append(percent)

        stop_event = threading.Event()

        mock_result = ElementResult(name="btn", bbox=(100, 100, 50, 30), confidence=0.9, strategy="test")

        with patch("subprocess.Popen"), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full", return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text", return_value=mock_result), \
             patch("execution.action_engine.ActionEngine.click"), \
             patch("automation.software_installer.INSTALL_STEPS", steps):
            run_software_installer(pkg, callback, stop_event)

    assert len(percents) > 0
    for p in percents:
        assert 0 <= p <= 100, f"percent {p} is out of [0, 100] range"


# ---------------------------------------------------------------------------
# Property 6: 停止信号终止安装步骤
# ---------------------------------------------------------------------------

@given(
    step_count=st.integers(min_value=2, max_value=8),
    stop_at=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=100)
def test_installer_stop_event_terminates_steps(step_count, stop_at):
    """Property 6: 停止信号终止安装步骤 — Validates: Requirements 2.5"""
    import tempfile
    from unittest.mock import MagicMock, patch
    from automation.software_installer import InstallStep, run_software_installer
    from perception.element_locator import ElementResult

    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "installer.exe"
        pkg.write_bytes(b"fake")

        steps = [InstallStep(f"按钮{i}", f"步骤{i}") for i in range(step_count)]

        call_count = 0
        stop_event = threading.Event()

        def callback(step: str, percent: int) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= stop_at:
                stop_event.set()

        mock_result = ElementResult(name="btn", bbox=(100, 100, 50, 30), confidence=0.9, strategy="test")

        with patch("subprocess.Popen"), \
             patch("perception.screen_capturer.ScreenCapturer.capture_full", return_value=MagicMock()), \
             patch("perception.element_locator.ElementLocator.locate_by_text", return_value=mock_result), \
             patch("execution.action_engine.ActionEngine.click"), \
             patch("automation.software_installer.INSTALL_STEPS", steps):
            run_software_installer(pkg, callback, stop_event)

    if stop_at < step_count:
        assert call_count <= stop_at + 1, (
            f"Expected at most {stop_at + 1} callbacks, got {call_count}"
        )


# ---------------------------------------------------------------------------
# Property 7: PythonAPI callback 同步更新进度和推送日志
# ---------------------------------------------------------------------------

@given(
    step_description=st.text(min_size=1, max_size=50),
    percent=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=100, deadline=None)
def test_python_api_callback_updates_progress_and_log(step_description, percent):
    """Property 7: PythonAPI callback 同步更新进度和推送日志 — Validates: Requirements 3.2, 3.3"""
    import time
    from unittest.mock import MagicMock, patch
    from gui.app import PythonAPI
    from gui.progress_manager import ProgressManager
    from ui.queue_manager import QueueManager

    pm = ProgressManager()
    qm = MagicMock(spec=QueueManager)
    api = PythonAPI(pm, qm)
    mock_win = MagicMock()
    api._main_win = mock_win

    updates: list[tuple] = []
    original_update = pm.update

    def tracking_update(p, s, task_name="", is_running=True):
        updates.append((p, s, task_name, is_running))
        original_update(p, s, task_name, is_running)

    pm.update = tracking_update

    with patch("gui.app.run_file_organizer") as mock_fo:
        def fake_run(source, target, cb, stop_event, file_filters=None):
            cb(step_description, percent)

        mock_fo.side_effect = fake_run
        api.start_file_organizer()
        time.sleep(0.15)

    # Property 7a: ProgressManager.update must have been called
    assert any(u[0] == percent and u[2] == "file_organizer" for u in updates), (
        f"ProgressManager.update not called with percent={percent}"
    )

    # Property 7b: evaluate_js("appendLog(...)") must have been called
    calls = [str(c) for c in mock_win.evaluate_js.call_args_list]
    assert any("appendLog" in c for c in calls), (
        "evaluate_js appendLog not called"
    )


# ---------------------------------------------------------------------------
# Property 8: 异常时 is_running 必须重置为 False
# ---------------------------------------------------------------------------

@given(
    error_msg=st.text(min_size=1, max_size=100),
)
@settings(max_examples=100)
def test_python_api_exception_resets_is_running(error_msg):
    """Property 8: 异常时 is_running 必须重置为 False — Validates: Requirements 3.5, 4.5"""
    import time
    from unittest.mock import MagicMock, patch
    from gui.app import PythonAPI
    from gui.progress_manager import ProgressManager
    from ui.queue_manager import QueueManager

    pm = ProgressManager()
    qm = MagicMock(spec=QueueManager)
    api = PythonAPI(pm, qm)
    api._main_win = MagicMock()

    with patch("gui.app.run_file_organizer") as mock_fo:
        mock_fo.side_effect = RuntimeError(error_msg)
        api.start_file_organizer()
        time.sleep(0.2)

    assert not pm.get().is_running, (
        f"is_running should be False after exception, got {pm.get().is_running}"
    )


# ---------------------------------------------------------------------------
# Property 9: ChatAgent 参数透传正确性
# ---------------------------------------------------------------------------

@given(
    source=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/\\_-.")),
    target=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/\\_-.")),
    filters=st.lists(st.sampled_from([".jpg", ".png", ".pdf", ".mp4", ".txt"]), max_size=5),
)
@settings(max_examples=100, deadline=None)
def test_chat_agent_passes_params_correctly(source, target, filters):
    """Property 9: ChatAgent 参数透传正确性 — Validates: Requirements 5.1"""
    import threading
    from unittest.mock import MagicMock, patch
    from gui.chat_agent import ChatAgent
    from gui.progress_manager import ProgressManager

    pm = ProgressManager()
    stop_event = threading.Event()
    messages = []
    agent = ChatAgent(
        llm_client=MagicMock(),
        progress_manager=pm,
        stop_event=stop_event,
        push_fn=lambda r, c: messages.append((r, c)),
    )

    with patch("automation.file_organizer.run_file_organizer") as mock_fo:
        mock_fo.return_value = None
        agent._run_file_organizer({"source": source, "target": target, "filters": filters})

    mock_fo.assert_called_once()
    call_args = mock_fo.call_args[0]
    assert call_args[0] == source, f"source mismatch: {call_args[0]} != {source}"
    assert call_args[1] == target, f"target mismatch: {call_args[1]} != {target}"
    assert call_args[4] == filters, f"filters mismatch: {call_args[4]} != {filters}"


# ---------------------------------------------------------------------------
# Property 10: 完成消息包含路径信息
# ---------------------------------------------------------------------------

@given(
    source=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/\\_-.")),
    target=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/\\_-.")),
)
@settings(max_examples=100)
def test_chat_agent_completion_message_contains_paths(source, target):
    """Property 10: 完成消息包含路径信息 — Validates: Requirements 5.3, 6.3"""
    import threading
    from unittest.mock import MagicMock, patch
    from gui.chat_agent import ChatAgent
    from gui.progress_manager import ProgressManager

    pm = ProgressManager()
    stop_event = threading.Event()
    messages = []
    agent = ChatAgent(
        llm_client=MagicMock(),
        progress_manager=pm,
        stop_event=stop_event,
        push_fn=lambda r, c: messages.append((r, c)),
    )

    with patch("automation.file_organizer.run_file_organizer") as mock_fo:
        mock_fo.return_value = None
        agent._run_file_organizer({"source": source, "target": target})

    assistant_msgs = [c for r, c in messages if r == "assistant"]
    assert len(assistant_msgs) >= 1, "Should have at least one assistant message"
    completion_msg = assistant_msgs[-1]
    assert source in completion_msg, f"source {source!r} not in completion message: {completion_msg!r}"
    assert target in completion_msg, f"target {target!r} not in completion message: {completion_msg!r}"
