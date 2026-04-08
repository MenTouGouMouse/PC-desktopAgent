"""tests/unit/test_vision_overlay_api.py

属性测试：ui/gradio_app.VisionOverlayAPI

Tasks 6.4, 6.5, 6.6 of the vision-overlay spec.
- 不 mock VisionOverlayAPI 本身，测试真实实现
- 只 mock 外部 I/O（ScreenCapturer.capture_full）
- 断言基于真实输入输出关系
"""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from config.config_loader import VisionBoxConfig
from ui.gradio_app import VisionOverlayAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_capturer_mock(h: int, w: int) -> MagicMock:
    """创建返回随机 BGR 图像的 ScreenCapturer mock。"""
    rng = np.random.default_rng(42)
    frame = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    mock = MagicMock()
    mock.capture_full.return_value = frame
    return mock


def _make_api(h: int = 200, w: int = 200, enabled: bool = True) -> tuple[VisionOverlayAPI, MagicMock]:
    """构造 VisionOverlayAPI 实例，返回 (api, capturer_mock)。"""
    config = VisionBoxConfig(
        enabled=enabled,
        color="red",
        show_confidence=True,
        confidence_threshold=0.5,
    )
    capturer = _make_capturer_mock(h, w)
    api = VisionOverlayAPI(capturer=capturer, vision_config=config)
    return api, capturer


# ---------------------------------------------------------------------------
# Task 6.4 — Property 6: get_screen_with_boxes 返回合法 base64 字符串
# Validates: Requirements 3.1, 3.2, 3.4
# ---------------------------------------------------------------------------


@given(
    h=st.integers(min_value=100, max_value=400),
    w=st.integers(min_value=100, max_value=400),
    show=st.booleans(),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.large_base_example])
def test_get_screen_with_boxes_returns_valid_base64(
    h: int, w: int, show: bool, seed: int
) -> None:
    """**Validates: Requirements 3.1, 3.2, 3.4**

    对任意图像尺寸和 show_boxes_flag 值，get_screen_with_boxes() 必须：
    - 返回非空字符串
    - 字符串可被 base64 解码
    - 解码后前两字节为 JPEG magic bytes b'\\xff\\xd8'
    """
    rng = np.random.default_rng(seed)
    frame = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)

    config = VisionBoxConfig(enabled=True, color="red", show_confidence=True, confidence_threshold=0.5)
    capturer = MagicMock()
    capturer.capture_full.return_value = frame
    api = VisionOverlayAPI(capturer=capturer, vision_config=config)

    # 设置 show_boxes_flag 直接赋值（不启动线程，避免副作用）
    api.show_boxes_flag = show

    result = api.get_screen_with_boxes()

    assert isinstance(result, str), f"返回值必须是 str，实际: {type(result)}"
    assert len(result) > 0, "返回值不能为空字符串"

    decoded = base64.b64decode(result)
    assert decoded[:2] == b"\xff\xd8", (
        f"解码后前两字节必须是 JPEG magic bytes \\xff\\xd8，实际: {decoded[:2]!r}"
    )


# ---------------------------------------------------------------------------
# Task 6.5 — Property 7: set_show_boxes 状态更新
# Validates: Requirements 3.3
# ---------------------------------------------------------------------------


@given(show=st.booleans())
@settings(max_examples=20, suppress_health_check=[HealthCheck.large_base_example])
def test_set_show_boxes_updates_flag(show: bool) -> None:
    """**Validates: Requirements 3.3**

    enabled=True 时，调用 set_show_boxes(show) 后 show_boxes_flag 必须等于 show。
    """
    api, _ = _make_api(enabled=True)

    # patch VisionOverlayController 避免真实线程启动
    with patch("ui.gradio_app.VisionOverlayController") as MockController:
        mock_ctrl = MagicMock()
        MockController.return_value = mock_ctrl

        api.set_show_boxes(show)

        assert api.show_boxes_flag == show, (
            f"set_show_boxes({show}) 后 show_boxes_flag 应为 {show}，实际: {api.show_boxes_flag}"
        )

        # 清理：停止线程（若已启动）
        if show:
            api.set_show_boxes(False)


# ---------------------------------------------------------------------------
# Task 6.6 — Property 8: enabled=False 时 set_show_boxes 无效
# Validates: Requirements 7.3
# ---------------------------------------------------------------------------


def test_set_show_boxes_disabled_config_has_no_effect() -> None:
    """**Validates: Requirements 7.3**

    vision_box.enabled=False 时，对任意 bool 值调用 set_show_boxes：
    - show_boxes_flag 始终保持 False
    - 不启动后台检测线程
    """
    api, _ = _make_api(enabled=False)

    with patch("ui.gradio_app.VisionOverlayController") as MockController:
        for value in [True, False, True, True, False]:
            api.set_show_boxes(value)
            assert api.show_boxes_flag is False, (
                f"enabled=False 时 set_show_boxes({value}) 不应修改 flag，"
                f"实际: {api.show_boxes_flag}"
            )

        # 确认没有创建 VisionOverlayController 实例
        MockController.assert_not_called()
