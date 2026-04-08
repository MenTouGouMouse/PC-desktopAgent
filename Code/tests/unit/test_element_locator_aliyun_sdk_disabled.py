"""
Bug Condition Exploration Test — Bug 1: 阿里云视觉 SDK 版本不匹配

这些测试在未修复代码上 MUST FAIL，失败即证明 bug 存在。
DO NOT fix the code when tests fail.

Expected outcome on UNFIXED code:
- _check_aliyun_sdk() returns True (bug: doesn't check for DetectImageElementsRequest)
- No WARNING log containing "阿里云视觉策略已禁用"

Validates: Requirements 1.1, 1.2
"""
from __future__ import annotations

import logging
import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Setup: mock alibabacloud SDK modules WITHOUT DetectImageElementsRequest
# ---------------------------------------------------------------------------

def _make_sdk_without_detect_request():
    """Create mock SDK modules that do NOT have DetectImageElementsRequest."""
    # Mock the top-level package
    mock_viapi = types.ModuleType("alibabacloud_viapi20230117")

    # Mock models WITHOUT DetectImageElementsRequest
    mock_models = types.ModuleType("alibabacloud_viapi20230117.models")
    # Deliberately NOT adding DetectImageElementsRequest

    mock_viapi.models = mock_models

    # Mock client submodule
    mock_client_mod = types.ModuleType("alibabacloud_viapi20230117.client")
    mock_viapi.client = mock_client_mod

    # Mock tea_openapi
    mock_tea = types.ModuleType("alibabacloud_tea_openapi")
    mock_tea_models = types.ModuleType("alibabacloud_tea_openapi.models")
    mock_tea.models = mock_tea_models

    return mock_viapi, mock_models, mock_client_mod, mock_tea, mock_tea_models


@pytest.fixture(autouse=True)
def reset_aliyun_sdk_cache():
    """Reset the module-level SDK availability cache before each test."""
    import perception.element_locator as el_mod
    original = el_mod._ALIYUN_SDK_AVAILABLE
    el_mod._ALIYUN_SDK_AVAILABLE = None  # Force re-detection
    yield
    el_mod._ALIYUN_SDK_AVAILABLE = original


@pytest.fixture
def screenshot() -> np.ndarray:
    return np.zeros((100, 100, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Test 1: _check_aliyun_sdk() returns False when DetectImageElementsRequest missing
# ---------------------------------------------------------------------------

class TestCheckAliyunSdkMissingClass:
    def test_check_aliyun_sdk_returns_false_when_class_missing(self):
        """
        Bug condition: alibabacloud_viapi20230117.models does NOT have DetectImageElementsRequest.

        EXPECTED OUTCOME on UNFIXED code: FAILS
        - Unfixed _check_aliyun_sdk() only checks if import succeeds, not if the class exists
        - Returns True even though DetectImageElementsRequest is missing
        - Fixed code should return False and log WARNING "阿里云视觉策略已禁用"
        """
        mock_viapi, mock_models, mock_client_mod, mock_tea, mock_tea_models = (
            _make_sdk_without_detect_request()
        )

        with patch.dict(sys.modules, {
            "alibabacloud_viapi20230117": mock_viapi,
            "alibabacloud_viapi20230117.models": mock_models,
            "alibabacloud_viapi20230117.client": mock_client_mod,
            "alibabacloud_tea_openapi": mock_tea,
            "alibabacloud_tea_openapi.models": mock_tea_models,
        }):
            from perception.element_locator import _check_aliyun_sdk
            result = _check_aliyun_sdk()

        # FAILS on unfixed code: unfixed returns True (only checks import, not class existence)
        assert result is False, (
            f"Expected _check_aliyun_sdk() to return False when DetectImageElementsRequest "
            f"is missing from models, but got {result!r}. "
            f"Bug: unfixed code only checks import success, not class existence."
        )

    def test_check_aliyun_sdk_logs_warning_when_class_missing(self, caplog):
        """
        Bug condition: SDK installed but DetectImageElementsRequest missing.

        EXPECTED OUTCOME on UNFIXED code: FAILS
        - Unfixed code does not log "阿里云视觉策略已禁用" in this scenario
        """
        mock_viapi, mock_models, mock_client_mod, mock_tea, mock_tea_models = (
            _make_sdk_without_detect_request()
        )

        with patch.dict(sys.modules, {
            "alibabacloud_viapi20230117": mock_viapi,
            "alibabacloud_viapi20230117.models": mock_models,
            "alibabacloud_viapi20230117.client": mock_client_mod,
            "alibabacloud_tea_openapi": mock_tea,
            "alibabacloud_tea_openapi.models": mock_tea_models,
        }):
            with caplog.at_level(logging.WARNING, logger="perception.element_locator"):
                from perception.element_locator import _check_aliyun_sdk
                _check_aliyun_sdk()

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("阿里云视觉策略已禁用" in msg for msg in warning_messages), (
            f"Expected WARNING log containing '阿里云视觉策略已禁用', "
            f"but got warnings: {warning_messages!r}. "
            f"Bug: unfixed code does not log SDK version mismatch."
        )


# ---------------------------------------------------------------------------
# Test 2: _locate_by_aliyun_vision returns None without AttributeError
# ---------------------------------------------------------------------------

class TestLocateByAliyunVisionSdkDisabled:
    def test_locate_returns_none_when_sdk_class_missing(self, screenshot):
        """
        Bug condition: SDK installed but DetectImageElementsRequest missing.

        EXPECTED OUTCOME on UNFIXED code: FAILS
        - Unfixed _check_aliyun_sdk() returns True (thinks SDK is OK)
        - Then _call_aliyun_detect_api tries to use DetectImageElementsRequest
        - Raises AttributeError, caught by outer except, returns None
        - But the test also checks for the WARNING log which is absent on unfixed code
        """
        mock_viapi, mock_models, mock_client_mod, mock_tea, mock_tea_models = (
            _make_sdk_without_detect_request()
        )

        with patch.dict(sys.modules, {
            "alibabacloud_viapi20230117": mock_viapi,
            "alibabacloud_viapi20230117.models": mock_models,
            "alibabacloud_viapi20230117.client": mock_client_mod,
            "alibabacloud_tea_openapi": mock_tea,
            "alibabacloud_tea_openapi.models": mock_tea_models,
        }):
            from perception.element_locator import ElementLocator
            locator = ElementLocator()
            # Should not raise AttributeError
            result = locator._locate_by_aliyun_vision(screenshot, "完成")

        assert result is None, (
            f"Expected _locate_by_aliyun_vision to return None when SDK class is missing, "
            f"but got {result!r}."
        )

    def test_locate_logs_warning_about_disabled_strategy(self, screenshot, caplog):
        """
        Bug condition: SDK installed but DetectImageElementsRequest missing.

        EXPECTED OUTCOME on UNFIXED code: FAILS
        - Unfixed code does not emit WARNING "阿里云视觉策略已禁用" in this path
        - It only logs a generic "API 调用异常" warning
        """
        mock_viapi, mock_models, mock_client_mod, mock_tea, mock_tea_models = (
            _make_sdk_without_detect_request()
        )

        with patch.dict(sys.modules, {
            "alibabacloud_viapi20230117": mock_viapi,
            "alibabacloud_viapi20230117.models": mock_models,
            "alibabacloud_viapi20230117.client": mock_client_mod,
            "alibabacloud_tea_openapi": mock_tea,
            "alibabacloud_tea_openapi.models": mock_tea_models,
        }):
            with caplog.at_level(logging.WARNING, logger="perception.element_locator"):
                from perception.element_locator import ElementLocator
                locator = ElementLocator()
                locator._locate_by_aliyun_vision(screenshot, "完成")

        all_messages = " ".join(r.message for r in caplog.records)
        assert "阿里云视觉策略已禁用" in all_messages, (
            f"Expected WARNING containing '阿里云视觉策略已禁用' in logs, "
            f"but got: {[r.message for r in caplog.records]!r}. "
            f"Bug: unfixed code does not log SDK version mismatch warning."
        )
