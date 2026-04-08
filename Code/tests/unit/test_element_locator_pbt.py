"""属性测试：ElementLocator 降级链编排。

覆盖属性：
- Property 3: 高优先级策略成功时低优先级策略不被调用
- Property 4: 策略失败时自动降级，全部失败时返回错误
- Property 5: 识别成功时返回完整 ElementResult 结构

# Feature: cv-desktop-automation-agent
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from perception.element_locator import ElementLocator, ElementResult, ElementNotFoundError


# ---------------------------------------------------------------------------
# Shared strategies & helpers
# ---------------------------------------------------------------------------

# Strategy for valid element description strings
element_description_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
    min_size=1,
    max_size=50,
)

# Strategy for valid bbox tuples (x, y, w, h) with positive dimensions
bbox_st = st.tuples(
    st.integers(min_value=0, max_value=1900),
    st.integers(min_value=0, max_value=1060),
    st.integers(min_value=1, max_value=200),
    st.integers(min_value=1, max_value=200),
)

# Strategy for valid confidence values
confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

# Strategy for valid strategy names
strategy_name_st = st.sampled_from(["aliyun_vision", "qwen_vl", "ocr", "template", "experience"])


def make_element_result(
    name: str = "按钮",
    bbox: tuple[int, int, int, int] = (10, 20, 30, 15),
    confidence: float = 0.9,
    strategy: str = "aliyun_vision",
) -> ElementResult:
    return ElementResult(name=name, bbox=bbox, confidence=confidence, strategy=strategy)


def make_locator() -> ElementLocator:
    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "test_id",
        "ALIYUN_ACCESS_KEY_SECRET": "test_secret",
        "DASHSCOPE_API_KEY": "test_key",
    }):
        return ElementLocator()


def make_screenshot(height: int = 100, width: int = 100) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Property 3: 高优先级策略成功时低优先级策略不被调用
# Feature: cv-desktop-automation-agent, Property 3: 高优先级策略成功时低优先级策略不被调用
# Validates: Requirements 2.1, 2.2
# ---------------------------------------------------------------------------

class TestProperty3HighPrioritySkipsLower:
    """当降级链中第 N 个策略成功时，第 N+1 及之后的策略不应被调用。"""

    @settings(max_examples=100)
    @given(
        description=element_description_st,
        bbox=bbox_st,
        confidence=confidence_st,
    )
    def test_aliyun_success_skips_qwen_vl_and_ocr(
        self,
        description: str,
        bbox: tuple[int, int, int, int],
        confidence: float,
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 3: 高优先级策略成功时低优先级策略不被调用
        locator = make_locator()
        screenshot = make_screenshot()
        aliyun_result = make_element_result(
            name=description, bbox=bbox, confidence=confidence, strategy="aliyun_vision"
        )

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=aliyun_result) as mock_aliyun, \
             patch.object(locator, "_locate_by_qwen_vl") as mock_qwen, \
             patch.object(locator, "_locate_by_ocr") as mock_ocr:
            result = locator.locate_by_text(screenshot, description)

        # 阿里云成功 → 立即返回，不调用后续策略
        mock_aliyun.assert_called_once()
        mock_qwen.assert_not_called()
        mock_ocr.assert_not_called()
        assert result.strategy == "aliyun_vision"

    @settings(max_examples=100)
    @given(
        description=element_description_st,
        bbox=bbox_st,
        confidence=confidence_st,
    )
    def test_qwen_vl_success_skips_ocr(
        self,
        description: str,
        bbox: tuple[int, int, int, int],
        confidence: float,
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 3: 高优先级策略成功时低优先级策略不被调用
        locator = make_locator()
        screenshot = make_screenshot()
        qwen_result = make_element_result(
            name=description, bbox=bbox, confidence=confidence, strategy="qwen_vl"
        )

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=qwen_result) as mock_qwen, \
             patch.object(locator, "_locate_by_ocr") as mock_ocr:
            result = locator.locate_by_text(screenshot, description)

        # Qwen-VL 成功 → 不调用 OCR
        mock_qwen.assert_called_once()
        mock_ocr.assert_not_called()
        assert result.strategy == "qwen_vl"

    @settings(max_examples=100)
    @given(
        description=element_description_st,
        bbox=bbox_st,
        confidence=confidence_st,
    )
    def test_aliyun_success_skips_template_matching(
        self,
        description: str,
        bbox: tuple[int, int, int, int],
        confidence: float,
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 3: 高优先级策略成功时低优先级策略不被调用
        locator = make_locator()
        screenshot = make_screenshot()
        template = make_screenshot(20, 20)
        aliyun_result = make_element_result(
            name=description, bbox=bbox, confidence=confidence, strategy="aliyun_vision"
        )

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=aliyun_result) as mock_aliyun, \
             patch.object(locator, "_locate_by_qwen_vl") as mock_qwen, \
             patch.object(locator, "_locate_by_template") as mock_tmpl:
            result = locator.locate_by_template(screenshot, template, description)

        mock_aliyun.assert_called_once()
        mock_qwen.assert_not_called()
        mock_tmpl.assert_not_called()
        assert result.strategy == "aliyun_vision"

    @settings(max_examples=100)
    @given(
        description=element_description_st,
        bbox=bbox_st,
        confidence=confidence_st,
    )
    def test_qwen_vl_success_skips_template_matching(
        self,
        description: str,
        bbox: tuple[int, int, int, int],
        confidence: float,
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 3: 高优先级策略成功时低优先级策略不被调用
        locator = make_locator()
        screenshot = make_screenshot()
        template = make_screenshot(20, 20)
        qwen_result = make_element_result(
            name=description, bbox=bbox, confidence=confidence, strategy="qwen_vl"
        )

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=qwen_result) as mock_qwen, \
             patch.object(locator, "_locate_by_template") as mock_tmpl:
            result = locator.locate_by_template(screenshot, template, description)

        mock_qwen.assert_called_once()
        mock_tmpl.assert_not_called()
        assert result.strategy == "qwen_vl"


# ---------------------------------------------------------------------------
# Property 4: 策略失败时自动降级，全部失败时返回错误
# Feature: cv-desktop-automation-agent, Property 4: 策略失败时自动降级，全部失败时返回错误
# Validates: Requirements 2.3, 2.4
# ---------------------------------------------------------------------------

class TestProperty4FallbackAndError:
    """策略失败时必须降级；全部失败时返回 ElementNotFoundError；
    found=True 但 coords=None 时必须视为失败并强制降级。"""

    @settings(max_examples=100)
    @given(description=element_description_st)
    def test_all_strategies_fail_raises_element_not_found(
        self, description: str
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 4: 策略失败时自动降级，全部失败时返回错误
        locator = make_locator()
        screenshot = make_screenshot()

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_ocr", return_value=None):
            with pytest.raises(ElementNotFoundError):
                locator.locate_by_text(screenshot, description)

    @settings(max_examples=100)
    @given(description=element_description_st)
    def test_all_strategies_fail_error_contains_tried_strategies(
        self, description: str
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 4: 策略失败时自动降级，全部失败时返回错误
        locator = make_locator()
        screenshot = make_screenshot()

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_ocr", return_value=None):
            with pytest.raises(ElementNotFoundError) as exc_info:
                locator.locate_by_text(screenshot, description)

        # 错误信息必须包含已尝试的策略列表
        err = exc_info.value
        assert err.tried_strategies is not None
        assert len(err.tried_strategies) > 0
        assert "aliyun_vision" in err.tried_strategies

    @settings(max_examples=100)
    @given(description=element_description_st)
    def test_aliyun_failure_triggers_qwen_vl(self, description: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 4: 策略失败时自动降级，全部失败时返回错误
        locator = make_locator()
        screenshot = make_screenshot()
        qwen_result = make_element_result(name=description, strategy="qwen_vl")

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None) as mock_aliyun, \
             patch.object(locator, "_locate_by_qwen_vl", return_value=qwen_result) as mock_qwen, \
             patch.object(locator, "_locate_by_ocr") as mock_ocr:
            result = locator.locate_by_text(screenshot, description)

        # 阿里云失败后必须调用 Qwen-VL
        mock_aliyun.assert_called_once()
        mock_qwen.assert_called_once()
        assert result.strategy == "qwen_vl"

    @settings(max_examples=100)
    @given(description=element_description_st)
    def test_qwen_vl_failure_triggers_ocr(self, description: str) -> None:
        # Feature: cv-desktop-automation-agent, Property 4: 策略失败时自动降级，全部失败时返回错误
        locator = make_locator()
        screenshot = make_screenshot()
        ocr_result = make_element_result(name=description, strategy="ocr")

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None) as mock_qwen, \
             patch.object(locator, "_locate_by_ocr", return_value=ocr_result) as mock_ocr:
            result = locator.locate_by_text(screenshot, description)

        mock_qwen.assert_called_once()
        mock_ocr.assert_called_once()
        assert result.strategy == "ocr"

    @settings(max_examples=100)
    @given(description=element_description_st)
    def test_found_true_coords_none_forces_fallback_in_aliyun(
        self, description: str
    ) -> None:
        """found=True 但 coords=None 时，阿里云策略必须返回 None 触发降级。
        这验证了 _locate_by_aliyun_vision 内部的双重校验逻辑。
        """
        # Feature: cv-desktop-automation-agent, Property 4: 策略失败时自动降级，全部失败时返回错误
        locator = make_locator()
        screenshot = make_screenshot()

        # _call_aliyun_detect_api 返回 found=True 但 coords=None
        with patch.object(
            locator,
            "_call_aliyun_detect_api",
            return_value={"found": True, "coords": None},
        ) as mock_api, \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None) as mock_qwen, \
             patch.object(locator, "_locate_by_ocr", return_value=None):
            with pytest.raises(ElementNotFoundError):
                locator.locate_by_text(screenshot, description)

        # 阿里云 API 被调用了，但因 coords=None 触发降级，Qwen-VL 也被调用
        mock_api.assert_called_once()
        mock_qwen.assert_called_once()

    @settings(max_examples=100)
    @given(description=element_description_st)
    def test_found_true_coords_none_forces_fallback_in_qwen_vl(
        self, description: str
    ) -> None:
        """found=True 但 coords=None 时，Qwen-VL 策略必须返回 None 触发降级。"""
        # Feature: cv-desktop-automation-agent, Property 4: 策略失败时自动降级，全部失败时返回错误
        locator = make_locator()
        screenshot = make_screenshot()

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(
                 locator,
                 "_call_qwen_vl_api",
                 return_value={"found": True, "coords": None},
             ) as mock_qwen_api, \
             patch.object(locator, "_locate_by_ocr", return_value=None) as mock_ocr:
            with pytest.raises(ElementNotFoundError):
                locator.locate_by_text(screenshot, description)

        mock_qwen_api.assert_called_once()
        mock_ocr.assert_called_once()

    @settings(max_examples=100)
    @given(description=element_description_st)
    def test_experience_coords_prevents_error_when_all_fail(
        self, description: str
    ) -> None:
        """所有策略失败但提供经验坐标时，不应抛出异常，应返回经验坐标结果。"""
        # Feature: cv-desktop-automation-agent, Property 4: 策略失败时自动降级，全部失败时返回错误
        locator = make_locator()
        screenshot = make_screenshot()

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_ocr", return_value=None):
            result = locator.locate_by_text(
                screenshot, description, experience_coords=(100, 200)
            )

        assert result is not None
        assert result.strategy == "experience"

    @settings(max_examples=100)
    @given(description=element_description_st)
    def test_template_chain_all_fail_raises_element_not_found(
        self, description: str
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 4: 策略失败时自动降级，全部失败时返回错误
        locator = make_locator()
        screenshot = make_screenshot()
        template = make_screenshot(20, 20)

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_template", return_value=None):
            with pytest.raises(ElementNotFoundError):
                locator.locate_by_template(screenshot, template, description)


# ---------------------------------------------------------------------------
# Property 5: 识别成功时返回完整 ElementResult 结构
# Feature: cv-desktop-automation-agent, Property 5: 识别成功时返回完整 ElementResult 结构
# Validates: Requirements 2.5
# ---------------------------------------------------------------------------

class TestProperty5CompleteElementResult:
    """成功识别时，返回的 ElementResult 必须包含非空的 name、bbox（四元组整数）、
    confidence（0.0~1.0 浮点数）和 strategy 字段。"""

    @settings(max_examples=100)
    @given(
        description=element_description_st,
        bbox=bbox_st,
        confidence=confidence_st,
        strategy=strategy_name_st,
    )
    def test_result_has_all_required_fields(
        self,
        description: str,
        bbox: tuple[int, int, int, int],
        confidence: float,
        strategy: str,
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 5: 识别成功时返回完整 ElementResult 结构
        locator = make_locator()
        screenshot = make_screenshot()
        mock_result = make_element_result(
            name=description, bbox=bbox, confidence=confidence, strategy=strategy
        )

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=mock_result):
            result = locator.locate_by_text(screenshot, description)

        # 所有字段必须存在且非空
        assert result.name is not None and result.name != ""
        assert result.bbox is not None
        assert len(result.bbox) == 4
        assert all(isinstance(v, int) for v in result.bbox)
        assert result.confidence is not None
        assert 0.0 <= result.confidence <= 1.0
        assert result.strategy is not None and result.strategy != ""

    @settings(max_examples=100)
    @given(
        description=element_description_st,
        bbox=bbox_st,
        confidence=confidence_st,
    )
    def test_result_name_matches_description(
        self,
        description: str,
        bbox: tuple[int, int, int, int],
        confidence: float,
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 5: 识别成功时返回完整 ElementResult 结构
        locator = make_locator()
        screenshot = make_screenshot()
        mock_result = make_element_result(
            name=description, bbox=bbox, confidence=confidence, strategy="aliyun_vision"
        )

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=mock_result):
            result = locator.locate_by_text(screenshot, description)

        # name 字段应与请求的描述一致
        assert result.name == description

    @settings(max_examples=100)
    @given(
        description=element_description_st,
        bbox=bbox_st,
        confidence=confidence_st,
        strategy=strategy_name_st,
    )
    def test_result_bbox_dimensions_are_positive(
        self,
        description: str,
        bbox: tuple[int, int, int, int],
        confidence: float,
        strategy: str,
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 5: 识别成功时返回完整 ElementResult 结构
        assume(bbox[2] > 0 and bbox[3] > 0)  # width and height must be positive
        locator = make_locator()
        screenshot = make_screenshot()
        mock_result = make_element_result(
            name=description, bbox=bbox, confidence=confidence, strategy=strategy
        )

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=mock_result):
            result = locator.locate_by_text(screenshot, description)

        x, y, w, h = result.bbox
        assert w > 0, "bbox width must be positive"
        assert h > 0, "bbox height must be positive"

    @settings(max_examples=100)
    @given(
        description=element_description_st,
        x=st.integers(min_value=0, max_value=1900),
        y=st.integers(min_value=0, max_value=1060),
    )
    def test_experience_result_has_complete_structure(
        self, description: str, x: int, y: int
    ) -> None:
        """经验坐标兜底策略返回的 ElementResult 也必须满足完整结构要求。"""
        # Feature: cv-desktop-automation-agent, Property 5: 识别成功时返回完整 ElementResult 结构
        locator = make_locator()
        screenshot = make_screenshot()

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=None), \
             patch.object(locator, "_locate_by_qwen_vl", return_value=None), \
             patch.object(locator, "_locate_by_ocr", return_value=None):
            result = locator.locate_by_text(
                screenshot, description, experience_coords=(x, y)
            )

        assert result.name is not None and result.name != ""
        assert result.bbox is not None and len(result.bbox) == 4
        assert all(isinstance(v, int) for v in result.bbox)
        assert 0.0 <= result.confidence <= 1.0
        assert result.strategy == "experience"

    @settings(max_examples=100)
    @given(
        description=element_description_st,
        bbox=bbox_st,
        confidence=confidence_st,
        strategy=strategy_name_st,
    )
    def test_locate_by_template_result_has_all_required_fields(
        self,
        description: str,
        bbox: tuple[int, int, int, int],
        confidence: float,
        strategy: str,
    ) -> None:
        # Feature: cv-desktop-automation-agent, Property 5: 识别成功时返回完整 ElementResult 结构
        locator = make_locator()
        screenshot = make_screenshot()
        template = make_screenshot(20, 20)
        mock_result = make_element_result(
            name=description, bbox=bbox, confidence=confidence, strategy=strategy
        )

        with patch.object(locator, "_locate_by_aliyun_vision", return_value=mock_result):
            result = locator.locate_by_template(screenshot, template, description)

        assert result.name is not None and result.name != ""
        assert result.bbox is not None and len(result.bbox) == 4
        assert all(isinstance(v, int) for v in result.bbox)
        assert 0.0 <= result.confidence <= 1.0
        assert result.strategy is not None and result.strategy != ""
