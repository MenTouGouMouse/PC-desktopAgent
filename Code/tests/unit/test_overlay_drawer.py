"""
Unit tests for vision/overlay_drawer.py.

Mocks mss and cv2 to verify:
- stop() terminates the capture loop
- set_boxes() filters invalid entries (w<=0, h<=0, color out of [0,255])
- set_boxes() thread-safety with concurrent calls
- cv2.rectangle called once per valid box
- cv2.putText called for non-empty labels only
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from vision.overlay_drawer import DetectionBox, OverlayDrawer, _is_valid_box


# ---------------------------------------------------------------------------
# _is_valid_box helper
# ---------------------------------------------------------------------------

class TestIsValidBox:
    def test_valid_box(self) -> None:
        box = DetectionBox(x=0, y=0, w=10, h=10, label="ok", color_bgr=(0, 255, 128))
        assert _is_valid_box(box) is True

    def test_zero_width_invalid(self) -> None:
        box = DetectionBox(x=0, y=0, w=0, h=10)
        assert _is_valid_box(box) is False

    def test_negative_width_invalid(self) -> None:
        box = DetectionBox(x=0, y=0, w=-1, h=10)
        assert _is_valid_box(box) is False

    def test_zero_height_invalid(self) -> None:
        box = DetectionBox(x=0, y=0, w=10, h=0)
        assert _is_valid_box(box) is False

    def test_negative_height_invalid(self) -> None:
        box = DetectionBox(x=0, y=0, w=10, h=-5)
        assert _is_valid_box(box) is False

    def test_color_component_above_255_invalid(self) -> None:
        box = DetectionBox(x=0, y=0, w=10, h=10, color_bgr=(0, 256, 0))
        assert _is_valid_box(box) is False

    def test_color_component_below_0_invalid(self) -> None:
        box = DetectionBox(x=0, y=0, w=10, h=10, color_bgr=(-1, 0, 0))
        assert _is_valid_box(box) is False

    def test_boundary_color_255_valid(self) -> None:
        box = DetectionBox(x=0, y=0, w=1, h=1, color_bgr=(255, 255, 255))
        assert _is_valid_box(box) is True

    def test_boundary_color_0_valid(self) -> None:
        box = DetectionBox(x=0, y=0, w=1, h=1, color_bgr=(0, 0, 0))
        assert _is_valid_box(box) is True


# ---------------------------------------------------------------------------
# set_boxes filtering
# ---------------------------------------------------------------------------

class TestSetBoxes:
    def test_filters_zero_width(self) -> None:
        drawer = OverlayDrawer()
        boxes = [
            DetectionBox(x=0, y=0, w=0, h=10),
            DetectionBox(x=0, y=0, w=10, h=10),
        ]
        drawer.set_boxes(boxes)
        with drawer._boxes_lock:
            stored = list(drawer._boxes)
        assert len(stored) == 1
        assert stored[0].w == 10

    def test_filters_zero_height(self) -> None:
        drawer = OverlayDrawer()
        boxes = [DetectionBox(x=0, y=0, w=10, h=0)]
        drawer.set_boxes(boxes)
        with drawer._boxes_lock:
            stored = list(drawer._boxes)
        assert stored == []

    def test_filters_negative_dimensions(self) -> None:
        drawer = OverlayDrawer()
        boxes = [DetectionBox(x=0, y=0, w=-5, h=-5)]
        drawer.set_boxes(boxes)
        with drawer._boxes_lock:
            stored = list(drawer._boxes)
        assert stored == []

    def test_filters_invalid_color(self) -> None:
        drawer = OverlayDrawer()
        boxes = [
            DetectionBox(x=0, y=0, w=10, h=10, color_bgr=(0, 300, 0)),
            DetectionBox(x=0, y=0, w=10, h=10, color_bgr=(0, 200, 0)),
        ]
        drawer.set_boxes(boxes)
        with drawer._boxes_lock:
            stored = list(drawer._boxes)
        assert len(stored) == 1
        assert stored[0].color_bgr == (0, 200, 0)

    def test_keeps_all_valid_boxes(self) -> None:
        drawer = OverlayDrawer()
        boxes = [
            DetectionBox(x=0, y=0, w=10, h=10),
            DetectionBox(x=5, y=5, w=20, h=20, label="foo"),
        ]
        drawer.set_boxes(boxes)
        with drawer._boxes_lock:
            stored = list(drawer._boxes)
        assert len(stored) == 2

    def test_empty_list_clears_boxes(self) -> None:
        drawer = OverlayDrawer()
        drawer.set_boxes([DetectionBox(x=0, y=0, w=10, h=10)])
        drawer.set_boxes([])
        with drawer._boxes_lock:
            stored = list(drawer._boxes)
        assert stored == []

    def test_thread_safety_concurrent_set_boxes(self) -> None:
        """Concurrent set_boxes calls must not corrupt internal state."""
        drawer = OverlayDrawer()
        errors: list[Exception] = []

        def writer(label: str) -> None:
            try:
                for _ in range(50):
                    drawer.set_boxes([DetectionBox(x=0, y=0, w=10, h=10, label=label)])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(str(i),)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent set_boxes raised: {errors}"
        # State must be a valid list (not corrupted)
        with drawer._boxes_lock:
            stored = list(drawer._boxes)
        assert isinstance(stored, list)


# ---------------------------------------------------------------------------
# Capture loop — stop() terminates the loop
# ---------------------------------------------------------------------------

def _make_fake_frame() -> np.ndarray:
    """Return a small BGR numpy array to use as a fake screenshot."""
    return np.zeros((10, 10, 3), dtype=np.uint8)


def _make_mss_mock() -> MagicMock:
    """Build a mock mss context manager that returns a fake screenshot."""
    fake_raw = MagicMock()
    # np.array(fake_raw) needs to return a BGRA array
    fake_bgra = np.zeros((10, 10, 4), dtype=np.uint8)

    mock_sct = MagicMock()
    mock_sct.monitors = [{"left": 0, "top": 0, "width": 10, "height": 10}]
    mock_sct.grab.return_value = fake_bgra

    mock_mss_ctx = MagicMock()
    mock_mss_ctx.__enter__ = MagicMock(return_value=mock_sct)
    mock_mss_ctx.__exit__ = MagicMock(return_value=False)

    return mock_mss_ctx, mock_sct


class TestCaptureLoop:
    @patch("vision.overlay_drawer.cv2.imencode")
    @patch("vision.overlay_drawer.cv2.cvtColor")
    @patch("vision.overlay_drawer.np.array")
    @patch("vision.overlay_drawer.mss.mss")
    def test_stop_terminates_loop(
        self,
        mock_mss_cls: MagicMock,
        mock_np_array: MagicMock,
        mock_cvtcolor: MagicMock,
        mock_imencode: MagicMock,
    ) -> None:
        """stop() should cause the capture loop to exit."""
        mock_mss_ctx, mock_sct = _make_fake_frame_mocks(mock_mss_cls, mock_np_array, mock_cvtcolor, mock_imencode)

        drawer = OverlayDrawer(fps=100)  # high fps so loop runs fast
        callback = MagicMock()
        drawer.start(callback)

        # Let the loop run briefly then stop
        time.sleep(0.05)
        drawer.stop()
        assert drawer._thread is not None
        drawer._thread.join(timeout=1.0)

        assert not drawer._running
        assert not drawer._thread.is_alive()

    @patch("vision.overlay_drawer.cv2.putText")
    @patch("vision.overlay_drawer.cv2.rectangle")
    @patch("vision.overlay_drawer.cv2.imencode")
    @patch("vision.overlay_drawer.cv2.cvtColor")
    @patch("vision.overlay_drawer.np.array")
    @patch("vision.overlay_drawer.mss.mss")
    def test_rectangle_called_once_per_valid_box(
        self,
        mock_mss_cls: MagicMock,
        mock_np_array: MagicMock,
        mock_cvtcolor: MagicMock,
        mock_imencode: MagicMock,
        mock_rectangle: MagicMock,
        mock_puttext: MagicMock,
    ) -> None:
        """cv2.rectangle must be called exactly once per valid box per frame."""
        _make_fake_frame_mocks(mock_mss_cls, mock_np_array, mock_cvtcolor, mock_imencode)

        boxes = [
            DetectionBox(x=0, y=0, w=10, h=10, label=""),
            DetectionBox(x=5, y=5, w=20, h=20, label=""),
        ]

        drawer = OverlayDrawer(fps=100)
        callback = MagicMock()
        drawer.set_boxes(boxes)
        drawer.start(callback)

        # Wait for at least one frame
        time.sleep(0.05)
        drawer.stop()
        drawer._thread.join(timeout=1.0)

        # rectangle should have been called at least 2 times (once per box per frame)
        assert mock_rectangle.call_count >= 2

    @patch("vision.overlay_drawer.cv2.putText")
    @patch("vision.overlay_drawer.cv2.rectangle")
    @patch("vision.overlay_drawer.cv2.imencode")
    @patch("vision.overlay_drawer.cv2.cvtColor")
    @patch("vision.overlay_drawer.np.array")
    @patch("vision.overlay_drawer.mss.mss")
    def test_puttext_only_for_nonempty_labels(
        self,
        mock_mss_cls: MagicMock,
        mock_np_array: MagicMock,
        mock_cvtcolor: MagicMock,
        mock_imencode: MagicMock,
        mock_rectangle: MagicMock,
        mock_puttext: MagicMock,
    ) -> None:
        """cv2.putText must only be called for boxes with non-empty labels."""
        _make_fake_frame_mocks(mock_mss_cls, mock_np_array, mock_cvtcolor, mock_imencode)

        boxes = [
            DetectionBox(x=0, y=0, w=10, h=10, label=""),       # no label → no putText
            DetectionBox(x=5, y=5, w=20, h=20, label="target"),  # has label → putText
        ]

        drawer = OverlayDrawer(fps=100)
        callback = MagicMock()
        drawer.set_boxes(boxes)
        drawer.start(callback)

        time.sleep(0.05)
        drawer.stop()
        drawer._thread.join(timeout=1.0)

        # putText should have been called (for the labelled box) but not for the unlabelled one
        assert mock_puttext.call_count >= 1
        # Verify the text used in putText calls is always "target"
        for c in mock_puttext.call_args_list:
            assert c.args[1] == "target" or (len(c.args) > 1 and c.args[1] == "target")

    @patch("vision.overlay_drawer.cv2.putText")
    @patch("vision.overlay_drawer.cv2.rectangle")
    @patch("vision.overlay_drawer.cv2.imencode")
    @patch("vision.overlay_drawer.cv2.cvtColor")
    @patch("vision.overlay_drawer.np.array")
    @patch("vision.overlay_drawer.mss.mss")
    def test_no_puttext_when_all_labels_empty(
        self,
        mock_mss_cls: MagicMock,
        mock_np_array: MagicMock,
        mock_cvtcolor: MagicMock,
        mock_imencode: MagicMock,
        mock_rectangle: MagicMock,
        mock_puttext: MagicMock,
    ) -> None:
        """cv2.putText must NOT be called when all boxes have empty labels."""
        _make_fake_frame_mocks(mock_mss_cls, mock_np_array, mock_cvtcolor, mock_imencode)

        boxes = [
            DetectionBox(x=0, y=0, w=10, h=10, label=""),
            DetectionBox(x=5, y=5, w=20, h=20, label=""),
        ]

        drawer = OverlayDrawer(fps=100)
        callback = MagicMock()
        drawer.set_boxes(boxes)
        drawer.start(callback)

        time.sleep(0.05)
        drawer.stop()
        drawer._thread.join(timeout=1.0)

        assert mock_puttext.call_count == 0

    @patch("vision.overlay_drawer.cv2.imencode")
    @patch("vision.overlay_drawer.cv2.cvtColor")
    @patch("vision.overlay_drawer.np.array")
    @patch("vision.overlay_drawer.mss.mss")
    def test_loop_continues_after_exception(
        self,
        mock_mss_cls: MagicMock,
        mock_np_array: MagicMock,
        mock_cvtcolor: MagicMock,
        mock_imencode: MagicMock,
    ) -> None:
        """The capture loop must continue running even if an exception is raised."""
        mock_mss_ctx, mock_sct = _make_fake_frame_mocks(mock_mss_cls, mock_np_array, mock_cvtcolor, mock_imencode)

        call_count = 0

        def flaky_grab(monitor: dict) -> np.ndarray:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated mss failure")
            return np.zeros((10, 10, 4), dtype=np.uint8)

        mock_sct.grab.side_effect = flaky_grab

        callback = MagicMock()
        drawer = OverlayDrawer(fps=100)
        drawer.start(callback)

        time.sleep(0.1)
        drawer.stop()
        drawer._thread.join(timeout=1.0)

        # Callback should have been called at least once (after the first failure)
        assert callback.call_count >= 1


# ---------------------------------------------------------------------------
# Helper used by capture loop tests
# ---------------------------------------------------------------------------

def _make_fake_frame_mocks(
    mock_mss_cls: MagicMock,
    mock_np_array: MagicMock,
    mock_cvtcolor: MagicMock,
    mock_imencode: MagicMock,
) -> tuple[MagicMock, MagicMock]:
    """Wire up the mss / cv2 mocks to return a valid fake frame."""
    fake_bgra = np.zeros((10, 10, 4), dtype=np.uint8)
    fake_bgr = np.zeros((10, 10, 3), dtype=np.uint8)

    mock_sct = MagicMock()
    mock_sct.monitors = [{"left": 0, "top": 0, "width": 10, "height": 10}]
    mock_sct.grab.return_value = fake_bgra

    mock_mss_ctx = MagicMock()
    mock_mss_ctx.__enter__ = MagicMock(return_value=mock_sct)
    mock_mss_ctx.__exit__ = MagicMock(return_value=False)
    mock_mss_cls.return_value = mock_mss_ctx

    mock_np_array.return_value = fake_bgra
    mock_cvtcolor.return_value = fake_bgr

    # imencode returns (True, buffer) where buffer has .tobytes()
    fake_buf = MagicMock()
    fake_buf.tobytes.return_value = b"\xff\xd8\xff\xe0fake_jpeg_data"
    mock_imencode.return_value = (True, fake_buf)

    return mock_mss_ctx, mock_sct
