"""感知层 → 执行层集成测试。

测试 ElementLocator.locate_by_text → ActionEngine.click 的完整数据流：
- 验证 ElementResult.bbox 中的逻辑坐标被正确传递给 ActionEngine.click
- 验证 ActionEngine.click 在调用 pyautogui.click 之前通过 DPIAdapter.to_physical 转换坐标
- 使用 tests/fixtures/screenshots/synthetic_800x600.png 作为截图 fixture
- mock 所有外部 API（阿里云、Qwen-VL）和 pyautogui，不产生真实鼠标操作

Requirements: 2.1, 6.4
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

from execution.action_engine import ActionEngine
from perception.dpi_adapter import DPIAdapter
from perception.element_locator import ElementLocator, ElementResult, ElementNotFoundError

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "screenshots"
SYNTHETIC_PNG = FIXTURES_DIR / "synthetic_800x600.png"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic_screenshot() -> np.ndarray:
    """加载预录制的合成截图（BGR numpy 数组）。

    若 PNG 文件不存在则动态生成，确保测试可独立运行。
    使用 np.fromfile + cv2.imdecode 避免 cv2.imread 在含中文路径下失败的问题。
    """
    import cv2

    if not SYNTHETIC_PNG.exists():
        # 动态生成：800×600 浅灰背景 + 蓝色按钮区域
        img = np.ones((600, 800, 3), dtype=np.uint8) * 200
        cv2.rectangle(img, (300, 250), (500, 300), (100, 100, 240), -1)
        cv2.rectangle(img, (300, 250), (500, 300), (50, 50, 180), 2)
        cv2.putText(img, "Install", (340, 282), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        # cv2.imwrite 也可能在中文路径下失败，改用 imencode + 二进制写入
        success, buf = cv2.imencode(".png", img)
        assert success, "合成截图编码失败"
        SYNTHETIC_PNG.write_bytes(buf.tobytes())

    # np.fromfile + imdecode 兼容含中文/空格的路径（Windows cv2.imread 限制）
    raw = np.fromfile(str(SYNTHETIC_PNG), dtype=np.uint8)
    img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    assert img is not None, f"无法加载截图 fixture：{SYNTHETIC_PNG}"
    return img


@pytest.fixture
def dpi_adapter_1x() -> DPIAdapter:
    """缩放比例 1.0 的 DPIAdapter（逻辑坐标 == 物理坐标）。"""
    return DPIAdapter(scale_factor=1.0)


@pytest.fixture
def dpi_adapter_125() -> DPIAdapter:
    """缩放比例 1.25 的 DPIAdapter。"""
    return DPIAdapter(scale_factor=1.25)


@pytest.fixture
def action_engine_1x(dpi_adapter_1x: DPIAdapter) -> ActionEngine:
    """使用 1x DPI 的 ActionEngine。"""
    return ActionEngine(dpi_adapter=dpi_adapter_1x)


@pytest.fixture
def action_engine_125(dpi_adapter_125: DPIAdapter) -> ActionEngine:
    """使用 1.25x DPI 的 ActionEngine。"""
    return ActionEngine(dpi_adapter=dpi_adapter_125)


@pytest.fixture
def locator() -> ElementLocator:
    """ElementLocator 实例（外部 API 将在各测试中 mock）。"""
    return ElementLocator()


# ---------------------------------------------------------------------------
# 辅助：构造 Aliyun API mock 返回值
# ---------------------------------------------------------------------------

def _aliyun_success_result(bbox: tuple[int, int, int, int], confidence: float = 0.95) -> dict:
    """构造阿里云 API 成功响应（found=True, coords 非 None）。"""
    x, y, w, h = bbox
    cx = x + w // 2
    cy = y + h // 2
    return {
        "found": True,
        "coords": [cx, cy],
        "bbox": list(bbox),
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# 集成测试：感知层 → 执行层完整数据流
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestPerceptionExecutionDataFlow:
    """验证 ElementLocator → ActionEngine 的完整数据流。

    Validates: Requirements 2.1, 6.4
    """

    def test_locate_then_click_passes_bbox_center_to_action_engine(
        self,
        locator: ElementLocator,
        action_engine_1x: ActionEngine,
        synthetic_screenshot: np.ndarray,
    ) -> None:
        """感知层返回的 bbox 中心坐标应被正确传递给 ActionEngine.click。

        数据流：ElementLocator.locate_by_text → ElementResult.bbox → ActionEngine.click
        """
        # bbox = (300, 250, 200, 50)，中心点 = (400, 275)
        expected_bbox = (300, 250, 200, 50)
        expected_cx = 300 + 200 // 2  # 400
        expected_cy = 250 + 50 // 2   # 275

        with patch.object(
            locator,
            "_call_aliyun_detect_api",
            return_value=_aliyun_success_result(expected_bbox),
        ):
            result = locator.locate_by_text(synthetic_screenshot, "安装按钮")

        assert result is not None
        assert result.bbox == expected_bbox
        assert result.strategy == "aliyun_vision"

        # 从 bbox 提取中心点，传给 ActionEngine.click
        bx, by, bw, bh = result.bbox
        cx = bx + bw // 2
        cy = by + bh // 2

        assert cx == expected_cx
        assert cy == expected_cy

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            success = action_engine_1x.click(cx, cy)

        assert success is True
        # 1x DPI：物理坐标 == 逻辑坐标
        mock_click.assert_called_once_with(expected_cx, expected_cy)

    def test_dpi_adapter_to_physical_called_before_pyautogui_click(
        self,
        locator: ElementLocator,
        dpi_adapter_1x: DPIAdapter,
        synthetic_screenshot: np.ndarray,
    ) -> None:
        """验证 Requirement 6.4：ActionEngine.click 在调用 pyautogui 前先调用 DPIAdapter.to_physical。

        Validates: Requirements 6.4
        """
        engine = ActionEngine(dpi_adapter=dpi_adapter_1x)
        call_order: list[str] = []

        original_to_physical = dpi_adapter_1x.to_physical

        def spy_to_physical(lx: int, ly: int, monitor_index: int = 0) -> tuple[int, int]:
            call_order.append("to_physical")
            return original_to_physical(lx, ly, monitor_index)

        dpi_adapter_1x.to_physical = spy_to_physical  # type: ignore[method-assign]

        bbox = (300, 250, 200, 50)
        with patch.object(
            locator,
            "_call_aliyun_detect_api",
            return_value=_aliyun_success_result(bbox),
        ):
            result = locator.locate_by_text(synthetic_screenshot, "安装按钮")

        bx, by, bw, bh = result.bbox
        cx, cy = bx + bw // 2, by + bh // 2

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click", side_effect=lambda *a, **kw: call_order.append("pyautogui.click")),
        ):
            engine.click(cx, cy)

        # to_physical 必须在 pyautogui.click 之前被调用
        assert "to_physical" in call_order
        assert "pyautogui.click" in call_order
        assert call_order.index("to_physical") < call_order.index("pyautogui.click")

    def test_dpi_125_physical_coordinates_applied_to_click(
        self,
        locator: ElementLocator,
        action_engine_125: ActionEngine,
        synthetic_screenshot: np.ndarray,
    ) -> None:
        """125% DPI 时，pyautogui.click 应收到物理坐标（逻辑坐标 × 1.25）。

        Validates: Requirements 6.4
        """
        bbox = (100, 80, 200, 50)  # 逻辑坐标
        with patch.object(
            locator,
            "_call_aliyun_detect_api",
            return_value=_aliyun_success_result(bbox),
        ):
            result = locator.locate_by_text(synthetic_screenshot, "安装按钮")

        bx, by, bw, bh = result.bbox
        lx = bx + bw // 2  # 200
        ly = by + bh // 2  # 105

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            action_engine_125.click(lx, ly)

        # 物理坐标 = round(logical * 1.25)
        expected_px = round(lx * 1.25)
        expected_py = round(ly * 1.25)
        mock_click.assert_called_once_with(expected_px, expected_py)

    def test_fallback_chain_ocr_strategy_used_when_api_fails(
        self,
        locator: ElementLocator,
        action_engine_1x: ActionEngine,
        synthetic_screenshot: np.ndarray,
    ) -> None:
        """Requirement 2.1：阿里云和 Qwen-VL 均失败时，降级到 OCR 策略。

        Validates: Requirements 2.1
        """
        ocr_bbox = (350, 260, 100, 30)
        ocr_result = ElementResult(
            name="安装按钮",
            bbox=ocr_bbox,
            confidence=0.75,
            strategy="ocr",
        )

        with (
            # 阿里云失败（无 API key）
            patch.object(locator, "_call_aliyun_detect_api", side_effect=RuntimeError("no key")),
            # Qwen-VL 失败
            patch.object(locator, "_call_qwen_vl_api", side_effect=RuntimeError("no key")),
            # OCR 成功
            patch.object(locator, "_locate_by_ocr", return_value=ocr_result),
        ):
            result = locator.locate_by_text(synthetic_screenshot, "安装按钮")

        assert result is not None
        assert result.strategy == "ocr"
        assert result.bbox == ocr_bbox

        bx, by, bw, bh = result.bbox
        cx, cy = bx + bw // 2, by + bh // 2

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            success = action_engine_1x.click(cx, cy)

        assert success is True
        mock_click.assert_called_once_with(cx, cy)

    def test_fallback_chain_experience_coords_as_last_resort(
        self,
        locator: ElementLocator,
        action_engine_1x: ActionEngine,
        synthetic_screenshot: np.ndarray,
    ) -> None:
        """Requirement 2.1：所有策略失败时，经验坐标作为兜底。

        Validates: Requirements 2.1
        """
        experience = (400, 275)

        with (
            patch.object(locator, "_call_aliyun_detect_api", side_effect=RuntimeError("no key")),
            patch.object(locator, "_call_qwen_vl_api", side_effect=RuntimeError("no key")),
            patch.object(locator, "_locate_by_ocr", return_value=None),
        ):
            result = locator.locate_by_text(
                synthetic_screenshot,
                "安装按钮",
                experience_coords=experience,
            )

        assert result is not None
        assert result.strategy == "experience"
        assert result.bbox[0] == experience[0]
        assert result.bbox[1] == experience[1]

        bx, by, _, _ = result.bbox
        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            success = action_engine_1x.click(bx, by)

        assert success is True
        mock_click.assert_called_once_with(bx, by)

    def test_all_strategies_fail_raises_element_not_found(
        self,
        locator: ElementLocator,
        synthetic_screenshot: np.ndarray,
    ) -> None:
        """Requirement 2.1：所有策略均失败且无经验坐标时，抛出 ElementNotFoundError。

        Validates: Requirements 2.1
        """
        with (
            patch.object(locator, "_call_aliyun_detect_api", side_effect=RuntimeError("no key")),
            patch.object(locator, "_call_qwen_vl_api", side_effect=RuntimeError("no key")),
            patch.object(locator, "_locate_by_ocr", return_value=None),
        ):
            with pytest.raises(ElementNotFoundError) as exc_info:
                locator.locate_by_text(synthetic_screenshot, "不存在的按钮")

        assert "aliyun_vision" in exc_info.value.tried_strategies
        assert "qwen_vl" in exc_info.value.tried_strategies
        assert "ocr" in exc_info.value.tried_strategies

    def test_aliyun_found_true_but_coords_none_triggers_fallback(
        self,
        locator: ElementLocator,
        action_engine_1x: ActionEngine,
        synthetic_screenshot: np.ndarray,
    ) -> None:
        """阿里云返回 found=True 但 coords=None 时，必须强制降级（不得使用该结果）。

        Validates: Requirements 2.1
        """
        ocr_bbox = (300, 250, 200, 50)
        ocr_result = ElementResult(
            name="安装按钮",
            bbox=ocr_bbox,
            confidence=0.8,
            strategy="ocr",
        )

        with (
            # 阿里云返回 found=True 但 coords=None（已知 pitfall）
            patch.object(
                locator,
                "_call_aliyun_detect_api",
                return_value={"found": True, "coords": None},
            ),
            patch.object(locator, "_call_qwen_vl_api", side_effect=RuntimeError("no key")),
            patch.object(locator, "_locate_by_ocr", return_value=ocr_result),
        ):
            result = locator.locate_by_text(synthetic_screenshot, "安装按钮")

        # 必须降级到 OCR，不能使用 coords=None 的阿里云结果
        assert result.strategy == "ocr"
        assert result.bbox == ocr_bbox

    def test_pyautogui_not_called_when_coordinates_out_of_bounds(
        self,
        locator: ElementLocator,
        action_engine_1x: ActionEngine,
        synthetic_screenshot: np.ndarray,
    ) -> None:
        """坐标超出屏幕边界时，pyautogui.click 不应被调用。"""
        # 返回超出 1920x1080 屏幕的坐标
        out_of_bounds_bbox = (2000, 1200, 10, 10)
        with patch.object(
            locator,
            "_call_aliyun_detect_api",
            return_value=_aliyun_success_result(out_of_bounds_bbox),
        ):
            result = locator.locate_by_text(synthetic_screenshot, "越界元素")

        bx, by, bw, bh = result.bbox
        cx, cy = bx + bw // 2, by + bh // 2

        with (
            patch("pyautogui.size", return_value=(1920, 1080)),
            patch("pyautogui.click") as mock_click,
        ):
            success = action_engine_1x.click(cx, cy)

        assert success is False
        mock_click.assert_not_called()
