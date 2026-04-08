"""ui/gradio_app.py 的单元测试。

覆盖 annotate_elements 辅助函数的核心行为，以及 build_app 的基本构建。
所有外部 I/O（屏幕截图、Gradio 启动）均通过 mock 隔离。
"""
from __future__ import annotations

from multiprocessing import Queue
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from perception.element_locator import ElementResult
from ui.gradio_app import annotate_elements, build_app


# ---------------------------------------------------------------------------
# annotate_elements
# ---------------------------------------------------------------------------

class TestAnnotateElements:
    """验证 annotate_elements 在 bbox 边界上绘制红色像素，且不修改原数组。"""

    def _make_black_frame(self, h: int = 100, w: int = 100) -> np.ndarray:
        return np.zeros((h, w, 3), dtype=np.uint8)

    def _make_element(self, x: int, y: int, w: int, h: int) -> ElementResult:
        return ElementResult(name="test", bbox=(x, y, w, h), confidence=0.9, strategy="test")

    # ------------------------------------------------------------------
    # 基本行为
    # ------------------------------------------------------------------

    def test_returns_copy_not_original(self) -> None:
        """annotate_elements 不应修改原始 frame。"""
        frame = self._make_black_frame()
        elem = self._make_element(10, 10, 20, 20)
        result = annotate_elements(frame, [elem])
        assert result is not frame

    def test_original_frame_unchanged(self) -> None:
        """原始 frame 在标注后保持全黑。"""
        frame = self._make_black_frame()
        elem = self._make_element(10, 10, 20, 20)
        annotate_elements(frame, [elem])
        assert np.all(frame == 0), "原始 frame 不应被修改"

    def test_empty_elements_returns_identical_copy(self) -> None:
        """无元素时返回与原始 frame 内容相同的副本。"""
        frame = self._make_black_frame()
        result = annotate_elements(frame, [])
        np.testing.assert_array_equal(result, frame)

    # ------------------------------------------------------------------
    # 红色像素验证（BGR: (0, 0, 255)）
    # ------------------------------------------------------------------

    def test_top_edge_has_red_pixels(self) -> None:
        """bbox 顶边上应有红色像素 BGR=(0,0,255)。"""
        frame = self._make_black_frame(200, 200)
        x, y, w, h = 20, 30, 50, 40
        elem = self._make_element(x, y, w, h)
        result = annotate_elements(frame, [elem])
        # 顶边：row=y, col in [x, x+w]
        top_row = result[y, x : x + w + 1]
        red_pixels = np.all(top_row == [0, 0, 255], axis=1)
        assert red_pixels.any(), "bbox 顶边应有红色像素"

    def test_bottom_edge_has_red_pixels(self) -> None:
        """bbox 底边上应有红色像素。"""
        frame = self._make_black_frame(200, 200)
        x, y, w, h = 20, 30, 50, 40
        elem = self._make_element(x, y, w, h)
        result = annotate_elements(frame, [elem])
        bottom_row = result[y + h, x : x + w + 1]
        red_pixels = np.all(bottom_row == [0, 0, 255], axis=1)
        assert red_pixels.any(), "bbox 底边应有红色像素"

    def test_left_edge_has_red_pixels(self) -> None:
        """bbox 左边上应有红色像素。"""
        frame = self._make_black_frame(200, 200)
        x, y, w, h = 20, 30, 50, 40
        elem = self._make_element(x, y, w, h)
        result = annotate_elements(frame, [elem])
        left_col = result[y : y + h + 1, x]
        red_pixels = np.all(left_col == [0, 0, 255], axis=1)
        assert red_pixels.any(), "bbox 左边应有红色像素"

    def test_right_edge_has_red_pixels(self) -> None:
        """bbox 右边上应有红色像素。"""
        frame = self._make_black_frame(200, 200)
        x, y, w, h = 20, 30, 50, 40
        elem = self._make_element(x, y, w, h)
        result = annotate_elements(frame, [elem])
        right_col = result[y : y + h + 1, x + w]
        red_pixels = np.all(right_col == [0, 0, 255], axis=1)
        assert red_pixels.any(), "bbox 右边应有红色像素"

    def test_interior_pixels_remain_black(self) -> None:
        """bbox 内部（非边界）像素不应被涂红（矩形框，非填充）。"""
        frame = self._make_black_frame(200, 200)
        x, y, w, h = 20, 30, 50, 40
        elem = self._make_element(x, y, w, h)
        result = annotate_elements(frame, [elem])
        # 取内部区域（去掉边界厚度 2px）
        thickness = 2
        interior = result[y + thickness + 1 : y + h - thickness, x + thickness + 1 : x + w - thickness]
        if interior.size > 0:
            assert np.all(interior == 0), "bbox 内部不应有红色像素"

    def test_area_outside_bbox_remains_black(self) -> None:
        """bbox 完全外部的区域不应引入红色像素。"""
        frame = self._make_black_frame(200, 200)
        x, y, w, h = 50, 50, 30, 30
        elem = self._make_element(x, y, w, h)
        result = annotate_elements(frame, [elem])
        # 左上角远离 bbox 的区域
        corner = result[0:10, 0:10]
        assert np.all(corner == 0), "bbox 外部不应有红色像素"

    # ------------------------------------------------------------------
    # 多元素
    # ------------------------------------------------------------------

    def test_multiple_elements_all_annotated(self) -> None:
        """多个元素时，每个 bbox 边界都应有红色像素。"""
        frame = self._make_black_frame(300, 300)
        elems = [
            self._make_element(10, 10, 30, 20),
            self._make_element(100, 100, 40, 40),
        ]
        result = annotate_elements(frame, elems)
        for elem in elems:
            ex, ey, ew, eh = elem.bbox
            top_row = result[ey, ex : ex + ew + 1]
            assert np.any(np.all(top_row == [0, 0, 255], axis=1)), (
                f"元素 {elem.name} bbox={elem.bbox} 顶边应有红色像素"
            )

    # ------------------------------------------------------------------
    # 颜色精确性：BGR (0, 0, 255)
    # ------------------------------------------------------------------

    def test_annotation_color_is_exactly_red_bgr(self) -> None:
        """标注颜色必须精确为 BGR (0, 0, 255)，不是其他颜色。"""
        frame = self._make_black_frame(100, 100)
        elem = self._make_element(10, 10, 30, 30)
        result = annotate_elements(frame, [elem])
        # 检查顶边中点像素
        mid_x = 10 + 15
        pixel = result[10, mid_x]
        assert pixel[0] == 0, f"B 通道应为 0，实际为 {pixel[0]}"
        assert pixel[1] == 0, f"G 通道应为 0，实际为 {pixel[1]}"
        assert pixel[2] == 255, f"R 通道应为 255，实际为 {pixel[2]}"


# ---------------------------------------------------------------------------
# build_app
# ---------------------------------------------------------------------------

class TestBuildApp:
    """验证 build_app 能正常构建 Gradio Blocks 实例。"""

    def test_build_app_returns_blocks_instance(self) -> None:
        """build_app 应返回 gr.Blocks 实例。"""
        import gradio as gr

        cmd_q: Queue = Queue()
        status_q: Queue = Queue()

        with patch("ui.gradio_app.ScreenCapturer"):
            app = build_app(cmd_q, status_q)

        assert isinstance(app, gr.Blocks)

    def test_build_app_accepts_queues(self) -> None:
        """build_app 接受 multiprocessing.Queue 参数，不抛出异常。"""
        cmd_q: Queue = Queue()
        status_q: Queue = Queue()

        with patch("ui.gradio_app.ScreenCapturer"):
            try:
                build_app(cmd_q, status_q)
            except Exception as exc:
                pytest.fail(f"build_app 不应抛出异常，但抛出了：{exc}")
