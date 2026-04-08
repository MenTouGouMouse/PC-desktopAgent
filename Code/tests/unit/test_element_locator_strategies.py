"""单元测试：ElementLocator 策略 3-5 及降级链编排。

覆盖场景：
- _locate_by_ocr：成功、未找到、异常
- _locate_by_template：成功、置信度不足、异常
- _locate_by_experience：始终返回结果
- locate_by_text：高优先级成功时不调用后续策略；全部失败时抛出 ElementNotFoundError
- locate_by_template：高优先级成功时不调用后续策略；全部失败时抛出 ElementNotFoundError
- 有经验坐标时全部失败不抛出异常
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import cv2
import numpy as np
import pytest

from perception.element_locator import ElementLocator, ElementResult, ElementNotFoundError


@pytest.fixture
def locator() -> ElementLocator:
    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "test_id",
        "ALIYUN_ACCESS_KEY_SECRET": "test_secret",
        "DASHSCOPE_API_KEY": "test_key",
    }):
        return ElementLocator()


@pytest.fixture
def screenshot() -> np.ndarray:
    return np.zeros((200, 200, 3), dtype=np.uint8)


@pytest.fixture
def template() -> np.ndarray:
    return np.zeros((20, 20, 3), dtype=np.uint8)


def _make_result(strategy: str = "aliyun_vision") -> ElementResult:
    return ElementResult(name="按钮", bbox=(10, 20, 30, 15), confidence=0.9, strategy=strategy)


# ---------------------------------------------------------------------------
# 策略 3：_locate_by_ocr
# ---------------------------------------------------------------------------

class TestLocateByOcr:
    def test_success_returns_element_result(self, locator: ElementLocator, screenshot: np.ndarray) -> None:
        """OCR 找到目标文本时，应返回 strategy='ocr' 的 ElementResult。"""
        ocr_result = ElementResult(name="安装", bbox=(5, 10, 20, 10), confidence=0.8, strategy="ocr")
        mock_ocr_instance = MagicMock()
        mock_ocr_instance.find_text_bbox.return_value = ocr_result
        mock_ocr_class = MagicMock(return_value=mock_ocr_instance)
        with patch.dict("sys.modules", {"perception.ocr_helper": MagicMock(OCRHelper=mock_ocr_class)}):
            result = locator._locate_by_ocr(screenshot, "安装")
        assert result is not None
        assert result.strategy == "ocr"
        assert result.bbox == (5, 10, 20, 10)

    def test_not_found_returns_none(self, locator: ElementLocator, screenshot: np.ndarray) -> None:
        """OCR 未找到目标文本时，应返回 None。"""
        mock_ocr_instance = MagicMock()
        mock_ocr_instance.find_text_bbox.return_value = None
        mock_ocr_class = MagicMock(return_value=mock_ocr_instance)
        with patch.dict("sys.modules", {"perception.ocr_helper": MagicMock(OCRHelper=mock_ocr_class)}):
            result = locator._locate_by_ocr(screenshot, "不存在")
        assert result is None

    def test_exception_returns_none(self, locator: ElementLocator, screenshot: np.ndarray) -> None:
        """OCRHelper 抛出异常时，应捕获并返回 None。"""
        mock_ocr_module = MagicMock()
        mock_ocr_module.OCRHelper.side_effect = ImportError("no tesseract")
        with patch.dict("sys.modules", {"perception.ocr_helper": mock_ocr_module}):
            result = locator._locate_by_ocr(screenshot, "安装")
        assert result is None


# ---------------------------------------------------------------------------
# 策略 4：_locate_by_template
# ---------------------------------------------------------------------------

class TestLocateByTemplate:
    def test_success_above_threshold(self, locator: ElementLocator, screenshot: np.ndarray, template: np.ndarray) -> None:
        """模板匹配置信度 ≥ threshold 时，应返回正确的 ElementResult。"""
        import cv2
        # matchTemplate returns a result array; minMaxLoc returns (min, max, min_loc, max_loc)
        fake_result = np.array([[0.9]], dtype=np.float32)
        with patch("cv2.matchTemplate", return_value=fake_result), \
             patch("cv2.minMaxLoc", return_value=(0.0, 0.9, (0, 0), (5, 10))):
            result = locator._locate_by_template(screenshot, template, "按钮", threshold=0.8)
        assert result is not None
        assert result.strategy == "template"
        assert result.confidence == pytest.approx(0.9)
        assert result.bbox[0] == 5
        assert result.bbox[1] == 10

    def test_below_threshold_returns_none(self, locator: ElementLocator, screenshot: np.ndarray, template: np.ndarray) -> None:
        """置信度低于 threshold 时，应返回 None。"""
        fake_result = np.array([[0.5]], dtype=np.float32)
        with patch("cv2.matchTemplate", return_value=fake_result), \
             patch("cv2.minMaxLoc", return_value=(0.0, 0.5, (0, 0), (0, 0))):
            result = locator._locate_by_template(screenshot, template, "按钮", threshold=0.8)
        assert result is None

    def test_exception_returns_none(self, locator: ElementLocator, screenshot: np.ndarray, template: np.ndarray) -> None:
        """cv2.matchTemplate 抛出异常时，应返回 None。"""
        with patch("cv2.matchTemplate", side_effect=cv2.error("template error")):
            result = locator._locate_by_template(screenshot, template, "按钮")
        assert result is None


# ---------------------------------------------------------------------------
# 策略 5：_locate_by_experience
# ---------------------------------------------------------------------------

class TestLocateByExperience:
    def test_always_returns_result(self, locator: ElementLocator) -> None:
        """经验坐标策略应始终返回 ElementResult，置信度为 0.3。"""
        result = locator._locate_by_experience("按钮", (100, 200))
        assert result is not None
        assert result.strategy == "experience"
        assert result.confidence == pytest.approx(0.3)
        assert result.bbox[0] == 100
        assert result.bbox[1] == 200

    def test_name_preserved(self, locator: ElementLocator) -> None:
        result = locator._locate_by_experience("安装按钮", (50, 60))
        assert result.name == "安装按钮"


# ---------------------------------------------------------------------------
# locate_by_text — 降级链编排
# ---------------------------------------------------------------------------

class TestLocateByText:
    def test_aliyun_success_skips_lower_priority(self, locator: ElementLocator, screenshot: np.ndarray) -> None:
        """阿里云策略成功时，不应调用 Qwen-VL 或 OCR。"""
        aliyun_result = _make_result("aliyun_vision")
        with patch.object(locator, "_locate_by_aliyun_vision", return_value=aliyun_result) as mock_aliyun, \
             patch.object(locator, "_locate_by_qwen_vl") as mock_qwen, \
             patch.object(locator, "_locate_by_ocr") as mock_ocr:
            result = locator.locate_by_text(screenshot, "按钮")
        assert result.strategy == "aliyun_vision"
        mock_aliyun.assert_called_once()
        mock_qwen.assert_not_called()
        mock_ocr.assert_not_called()

    def test_qwen_vl_success_skips_ocr(self, locator: ElementLocator, screenshot: np.ndarray) -> None:
        """阿里云失败、Qwen-VL 成功时，不应调用 OCR。"""
        qwen_result = _make_result("qwen_vl")
        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=qwen_result) as mock_qwen, \
             patch.object(locator, "_locate_by_ocr") as mock_ocr:
            result = locator.locate_by_text(screenshot, "按钮")
        assert result.strategy == "qwen_vl"
        mock_qwen.assert_called_once()
        mock_ocr.assert_not_called()

    def test_ocr_success_returns_result(self, locator: ElementLocator, screenshot: np.ndarray) -> None:
        """前两个策略失败、OCR 成功时，应返回 OCR 结果。"""
        ocr_result = _make_result("ocr")
        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_ocr", return_value=ocr_result):
            result = locator.locate_by_text(screenshot, "按钮")
        assert result.strategy == "ocr"

    def test_all_fail_raises_element_not_found(self, locator: ElementLocator, screenshot: np.ndarray) -> None:
        """所有策略失败且无经验坐标时，应抛出 ElementNotFoundError。"""
        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_ocr", return_value=None):
            with pytest.raises(ElementNotFoundError) as exc_info:
                locator.locate_by_text(screenshot, "不存在的按钮")
        assert "aliyun_vision" in exc_info.value.tried_strategies
        assert "qwen_vl" in exc_info.value.tried_strategies
        assert "ocr" in exc_info.value.tried_strategies

    def test_all_fail_with_experience_coords_returns_result(self, locator: ElementLocator, screenshot: np.ndarray) -> None:
        """所有策略失败但提供经验坐标时，应返回经验坐标结果，不抛出异常。"""
        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_ocr", return_value=None):
            result = locator.locate_by_text(screenshot, "按钮", experience_coords=(100, 200))
        assert result.strategy == "experience"
        assert result.confidence == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# locate_by_template — 降级链编排
# ---------------------------------------------------------------------------

class TestLocateByTemplate:
    def test_aliyun_success_skips_template_matching(self, locator: ElementLocator, screenshot: np.ndarray, template: np.ndarray) -> None:
        """阿里云策略成功时，不应调用 OpenCV 模板匹配。"""
        aliyun_result = _make_result("aliyun_vision")
        with patch.object(locator, "_locate_by_aliyun_vision", return_value=aliyun_result), \
             patch.object(locator, "_locate_by_template") as mock_tmpl:
            result = locator.locate_by_template(screenshot, template, "按钮")
        assert result.strategy == "aliyun_vision"
        mock_tmpl.assert_not_called()

    def test_template_match_success_after_api_failures(self, locator: ElementLocator, screenshot: np.ndarray, template: np.ndarray) -> None:
        """前两个 API 策略失败、模板匹配成功时，应返回模板匹配结果。"""
        tmpl_result = _make_result("template")
        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_template", return_value=tmpl_result):
            result = locator.locate_by_template(screenshot, template, "按钮")
        assert result.strategy == "template"

    def test_all_fail_raises_element_not_found(self, locator: ElementLocator, screenshot: np.ndarray, template: np.ndarray) -> None:
        """所有策略失败且无经验坐标时，应抛出 ElementNotFoundError。"""
        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_template", return_value=None):
            with pytest.raises(ElementNotFoundError):
                locator.locate_by_template(screenshot, template, "按钮")

    def test_experience_coords_fallback(self, locator: ElementLocator, screenshot: np.ndarray, template: np.ndarray) -> None:
        """所有策略失败但提供经验坐标时，应返回经验坐标结果。"""
        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_template", return_value=None):
            result = locator.locate_by_template(screenshot, template, "按钮", experience_coords=(50, 75))
        assert result.strategy == "experience"


# ---------------------------------------------------------------------------
# ElementNotFoundError — tried_strategies 包含上下文
# ---------------------------------------------------------------------------

class TestElementNotFoundError:
    def test_str_includes_tried_strategies(self) -> None:
        err = ElementNotFoundError("找不到", tried_strategies=["aliyun_vision", "ocr"])
        assert "aliyun_vision" in str(err)
        assert "ocr" in str(err)

    def test_str_without_strategies(self) -> None:
        err = ElementNotFoundError("找不到")
        assert "找不到" in str(err)
