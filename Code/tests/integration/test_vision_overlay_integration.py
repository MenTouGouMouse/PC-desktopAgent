"""集成测试：VisionOverlayAPI 端到端数据流验证。

测试真实 VisionOverlayAPI 实现，只 mock 外部 I/O（ScreenCapturer.capture_full）。
断言基于真实输入输出关系。
"""
from __future__ import annotations

import base64
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from config.config_loader import VisionBoxConfig
from ui.gradio_app import VisionOverlayAPI


def _make_fake_frame(height: int = 200, width: int = 300) -> np.ndarray:
    """返回固定尺寸的 BGR uint8 numpy 图像（全黑）。"""
    return np.zeros((height, width, 3), dtype=np.uint8)


def _build_api(
    fake_frame: np.ndarray | None = None,
    vision_config: VisionBoxConfig | None = None,
) -> tuple[VisionOverlayAPI, MagicMock]:
    """构造 VisionOverlayAPI，capturer.capture_full 返回 fake_frame。

    Returns:
        (api, mock_capturer) 元组。
    """
    if fake_frame is None:
        fake_frame = _make_fake_frame()

    mock_capturer = MagicMock()
    mock_capturer.capture_full.return_value = fake_frame

    if vision_config is None:
        vision_config = VisionBoxConfig(enabled=True)

    api = VisionOverlayAPI(capturer=mock_capturer, vision_config=vision_config)
    return api, mock_capturer


# ---------------------------------------------------------------------------
# Task 8.1 — test_get_screen_with_boxes_returns_valid_base64
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_screen_with_boxes_returns_valid_base64() -> None:
    """get_screen_with_boxes() 在 show_boxes=True 时返回可解码的 base64 JPEG。

    Requirements: 3.1, 3.4
    """
    fake_frame = _make_fake_frame(200, 300)
    api, _ = _build_api(fake_frame=fake_frame)

    api.set_show_boxes(True)
    try:
        result = api.get_screen_with_boxes()

        # 断言返回非空字符串
        assert isinstance(result, str)
        assert len(result) > 0

        # 断言 base64 解码后前两字节为 JPEG magic bytes
        decoded = base64.b64decode(result)
        assert decoded[:2] == b"\xff\xd8", (
            f"Expected JPEG magic bytes \\xff\\xd8, got {decoded[:2]!r}"
        )
    finally:
        api.set_show_boxes(False)


# ---------------------------------------------------------------------------
# Task 8.2 — test_get_screen_with_boxes_flag_false_returns_raw
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_screen_with_boxes_flag_false_returns_raw() -> None:
    """get_screen_with_boxes() 在 show_boxes=False 时返回原始截图的 base64 字符串。

    Requirements: 3.2
    """
    fake_frame = _make_fake_frame(200, 300)
    api, _ = _build_api(fake_frame=fake_frame)

    api.set_show_boxes(False)
    result = api.get_screen_with_boxes()

    # 断言返回非空字符串且可 base64 解码
    assert isinstance(result, str)
    assert len(result) > 0
    decoded = base64.b64decode(result)
    assert len(decoded) > 0


# ---------------------------------------------------------------------------
# Task 8.3 — Property 10: 缓存限速
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_detection_rate_limiting() -> None:
    """快速连续调用 get_screen_with_boxes() 不超过检测频率上限。

    VisionOverlayController 后台线程以 detect_interval_sec=0.5 限速，
    get_screen_with_boxes 本身只读缓存，不直接调用 detect。
    20 次快速调用 + 等待 0.1s，detect 调用次数应 ≤ 2。

    Validates: Requirements 4.2, 4.4
    """
    fake_frame = _make_fake_frame(200, 300)
    mock_capturer = MagicMock()
    mock_capturer.capture_full.return_value = fake_frame

    vision_config = VisionBoxConfig(enabled=True)
    api = VisionOverlayAPI(capturer=mock_capturer, vision_config=vision_config)

    with patch(
        "automation.object_detector.detect_objects_for_display",
        return_value=[],
    ) as mock_detect:
        # 构造 controller 时使用较长的检测间隔，确保限速生效
        api.set_show_boxes(True)
        try:
            # 快速连续调用 20 次（不 sleep）
            for _ in range(20):
                api.get_screen_with_boxes()

            # 等待 0.1 秒（远小于 detect_interval_sec=0.5）
            time.sleep(0.1)

            # 断言 detect 调用次数 ≤ 2（后台线程在 0.1s 内最多触发 1 次）
            assert mock_detect.call_count <= 2, (
                f"detect_objects_for_display called {mock_detect.call_count} times, "
                f"expected ≤ 2 within 0.1s window"
            )
        finally:
            api.set_show_boxes(False)


# ---------------------------------------------------------------------------
# Task 8.4 — test_set_show_boxes_false_clears_cache
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_set_show_boxes_false_clears_cache() -> None:
    """set_show_boxes(False) 后缓存被清空，cache.get() 返回 []。

    Requirements: 6.3
    """
    fake_frame = _make_fake_frame(200, 300)
    api, _ = _build_api(fake_frame=fake_frame)

    api.set_show_boxes(True)
    try:
        # 手动向缓存写入数据
        api._detection_cache.update(
            [{"bbox": [0, 0, 10, 10], "label": "test_obj", "confidence": 0.9}]
        )
        # 确认缓存非空
        assert len(api._detection_cache.get()) == 1
    finally:
        # set_show_boxes(False) 应清空缓存
        api.set_show_boxes(False)

    assert api._detection_cache.get() == [], (
        "Expected cache to be empty after set_show_boxes(False)"
    )
