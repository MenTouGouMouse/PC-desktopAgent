"""单元测试：ElementLocator._locate_by_aliyun_vision 阿里云视觉策略（优先级 1）。

覆盖场景：
- 正常识别成功（found=True, coords 非 None）
- found=True 但 coords=None → 强制降级，返回 None
- found=False → 返回 None
- API 调用抛出异常 → 返回 None
- 图像编码失败 → 返回 None
- 响应包含 bbox 字段时正确解析
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from perception.element_locator import ElementLocator, ElementResult


@pytest.fixture
def locator() -> ElementLocator:
    """返回一个 ElementLocator 实例，注入假凭证。"""
    with (
        patch.dict(
            "os.environ",
            {
                "ALIYUN_ACCESS_KEY_ID": "test_key_id",
                "ALIYUN_ACCESS_KEY_SECRET": "test_key_secret",
            },
        )
    ):
        return ElementLocator()


@pytest.fixture
def black_screenshot() -> np.ndarray:
    """返回一张 100×100 的黑色 BGR 截图。"""
    return np.zeros((100, 100, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# 正常路径：识别成功
# ---------------------------------------------------------------------------


def test_locate_by_aliyun_vision_success_with_coords(
    locator: ElementLocator,
    black_screenshot: np.ndarray,
) -> None:
    """API 返回 found=True 且 coords 非 None 时，应返回 ElementResult。"""
    api_response = {"found": True, "coords": [50, 60], "confidence": 0.95}

    with patch.object(locator, "_call_aliyun_detect_api", return_value=api_response):
        result = locator._locate_by_aliyun_vision(black_screenshot, "安装按钮")

    assert result is not None
    assert isinstance(result, ElementResult)
    assert result.name == "安装按钮"
    assert result.strategy == "aliyun_vision"
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.bbox) == 4


def test_locate_by_aliyun_vision_success_with_bbox(
    locator: ElementLocator,
    black_screenshot: np.ndarray,
) -> None:
    """API 响应包含 bbox 字段时，bbox 应被正确解析为 (x, y, w, h)。"""
    api_response = {
        "found": True,
        "coords": [110, 120],
        "bbox": [100, 110, 20, 20],
        "confidence": 0.88,
    }

    with patch.object(locator, "_call_aliyun_detect_api", return_value=api_response):
        result = locator._locate_by_aliyun_vision(black_screenshot, "确认按钮")

    assert result is not None
    assert result.bbox == (100, 110, 20, 20)
    assert abs(result.confidence - 0.88) < 1e-6


# ---------------------------------------------------------------------------
# 降级路径：found=True 但 coords=None
# ---------------------------------------------------------------------------


def test_locate_by_aliyun_vision_found_true_coords_none_returns_none(
    locator: ElementLocator,
    black_screenshot: np.ndarray,
) -> None:
    """API 返回 found=True 但 coords=None 时，必须返回 None 触发降级。"""
    api_response = {"found": True, "coords": None}

    with patch.object(locator, "_call_aliyun_detect_api", return_value=api_response):
        result = locator._locate_by_aliyun_vision(black_screenshot, "安装按钮")

    assert result is None


def test_locate_by_aliyun_vision_found_false_returns_none(
    locator: ElementLocator,
    black_screenshot: np.ndarray,
) -> None:
    """API 返回 found=False 时，应返回 None。"""
    api_response = {"found": False, "coords": None}

    with patch.object(locator, "_call_aliyun_detect_api", return_value=api_response):
        result = locator._locate_by_aliyun_vision(black_screenshot, "不存在的按钮")

    assert result is None


# ---------------------------------------------------------------------------
# 异常路径：API 调用抛出异常
# ---------------------------------------------------------------------------


def test_locate_by_aliyun_vision_api_exception_returns_none(
    locator: ElementLocator,
    black_screenshot: np.ndarray,
) -> None:
    """API 调用抛出任意异常时，应捕获并返回 None，不向上传播。"""
    with patch.object(
        locator,
        "_call_aliyun_detect_api",
        side_effect=RuntimeError("网络超时"),
    ):
        result = locator._locate_by_aliyun_vision(black_screenshot, "安装按钮")

    assert result is None


def test_locate_by_aliyun_vision_connection_error_returns_none(
    locator: ElementLocator,
    black_screenshot: np.ndarray,
) -> None:
    """网络连接错误时，应捕获并返回 None。"""
    import urllib.error

    with patch.object(
        locator,
        "_call_aliyun_detect_api",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        result = locator._locate_by_aliyun_vision(black_screenshot, "安装按钮")

    assert result is None


# ---------------------------------------------------------------------------
# 图像编码失败
# ---------------------------------------------------------------------------


def test_locate_by_aliyun_vision_encode_failure_returns_none(
    locator: ElementLocator,
    black_screenshot: np.ndarray,
) -> None:
    """cv2.imencode 失败时，应返回 None 而不是抛出异常。"""
    with patch("cv2.imencode", return_value=(False, None)):
        result = locator._locate_by_aliyun_vision(black_screenshot, "安装按钮")

    assert result is None


# ---------------------------------------------------------------------------
# 缺少凭证时 _call_aliyun_detect_api 抛出 RuntimeError
# ---------------------------------------------------------------------------


def test_call_aliyun_detect_api_missing_credentials_raises() -> None:
    """未配置 Access Key 时，_call_aliyun_detect_api 应抛出 RuntimeError。"""
    with patch.dict("os.environ", {}, clear=True):
        loc = ElementLocator()

    with pytest.raises(RuntimeError, match="ALIYUN_ACCESS_KEY_ID"):
        loc._call_aliyun_detect_api("base64data", "按钮")


# ---------------------------------------------------------------------------
# 日志记录验证
# ---------------------------------------------------------------------------


def test_locate_by_aliyun_vision_logs_warning_on_coords_none(
    locator: ElementLocator,
    black_screenshot: np.ndarray,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """found=True 但 coords=None 时，必须记录 WARNING 日志。"""
    import logging

    api_response = {"found": True, "coords": None}

    with patch.object(locator, "_call_aliyun_detect_api", return_value=api_response):
        with caplog.at_level(logging.WARNING, logger="perception.element_locator"):
            locator._locate_by_aliyun_vision(black_screenshot, "安装按钮")

    assert any("coords" in record.message or "降级" in record.message for record in caplog.records)


def test_locate_by_aliyun_vision_logs_warning_on_exception(
    locator: ElementLocator,
    black_screenshot: np.ndarray,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """API 异常时，必须记录 WARNING 日志。"""
    import logging

    with patch.object(
        locator,
        "_call_aliyun_detect_api",
        side_effect=RuntimeError("timeout"),
    ):
        with caplog.at_level(logging.WARNING, logger="perception.element_locator"):
            locator._locate_by_aliyun_vision(black_screenshot, "安装按钮")

    assert any("降级" in record.message or "异常" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# _call_aliyun_detect_api — HTTP 响应解析
# ---------------------------------------------------------------------------

import types as _types


def _make_sdk_mock(elements: list) -> tuple[MagicMock, MagicMock]:
    """构造模拟阿里云 SDK 的 client 和 response 对象。

    Returns:
        (mock_sdk_client_class, mock_response) 元组
    """
    mock_response = MagicMock()
    mock_body = MagicMock()
    mock_data = MagicMock()
    mock_data.elements = elements
    mock_body.data = mock_data
    mock_response.body = mock_body

    mock_sdk_client = MagicMock()
    mock_sdk_client.detect_image_elements.return_value = mock_response
    mock_sdk_client_class = MagicMock(return_value=mock_sdk_client)
    return mock_sdk_client_class, mock_response


def _patch_aliyun_sdk(elements: list):
    """返回 patch 上下文管理器，模拟阿里云 SDK 导入和调用。"""
    import sys
    import types

    mock_viapi_client = MagicMock()
    mock_viapi_models = MagicMock()
    mock_open_api_models = MagicMock()

    # Build mock response
    mock_response = MagicMock()
    mock_body = MagicMock()
    mock_data = MagicMock()
    mock_data.elements = elements
    mock_body.data = mock_data
    mock_response.body = mock_body

    mock_sdk_client = MagicMock()
    mock_sdk_client.detect_image_elements.return_value = mock_response
    mock_viapi_client.Client.return_value = mock_sdk_client

    viapi_module = types.ModuleType("alibabacloud_viapi20230117")
    viapi_module.client = mock_viapi_client
    viapi_module.models = mock_viapi_models

    tea_module = types.ModuleType("alibabacloud_tea_openapi")
    tea_module.models = mock_open_api_models

    return patch.dict("sys.modules", {
        "alibabacloud_viapi20230117": viapi_module,
        "alibabacloud_viapi20230117.client": mock_viapi_client,
        "alibabacloud_viapi20230117.models": mock_viapi_models,
        "alibabacloud_tea_openapi": tea_module,
        "alibabacloud_tea_openapi.models": mock_open_api_models,
    })


def test_call_aliyun_detect_api_empty_elements_returns_not_found() -> None:
    """响应中 elements 为空列表时，应返回 found=False。"""
    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "key",
        "ALIYUN_ACCESS_KEY_SECRET": "secret",
    }):
        loc = ElementLocator()

    with _patch_aliyun_sdk(elements=[]):
        result = loc._call_aliyun_detect_api("b64data", "按钮")

    assert result["found"] is False
    assert result["coords"] is None


def test_call_aliyun_detect_api_element_with_box_returns_coords() -> None:
    """响应中 element 包含 box 属性时，应正确解析坐标和 bbox。"""
    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "key",
        "ALIYUN_ACCESS_KEY_SECRET": "secret",
    }):
        loc = ElementLocator()

    # Build element mock with box attribute (SDK object style)
    mock_element = MagicMock()
    mock_box = MagicMock()
    mock_box.x = 100
    mock_box.y = 200
    mock_box.width = 50
    mock_box.height = 30
    mock_element.box = mock_box
    mock_element.score = 0.92

    with _patch_aliyun_sdk(elements=[mock_element]):
        result = loc._call_aliyun_detect_api("b64data", "按钮")

    assert result["found"] is True
    assert result["coords"] == [125, 215]   # cx = 100 + 50//2, cy = 200 + 30//2
    assert result["bbox"] == [100, 200, 50, 30]
    assert abs(result["confidence"] - 0.92) < 1e-6


def test_call_aliyun_detect_api_element_without_box_returns_coords_none() -> None:
    """响应中 element 没有 box 属性时，应返回 found=True, coords=None。"""
    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "key",
        "ALIYUN_ACCESS_KEY_SECRET": "secret",
    }):
        loc = ElementLocator()

    # Element with no box attribute
    mock_element = MagicMock(spec=[])  # spec=[] means no attributes
    mock_element.score = 0.8

    with _patch_aliyun_sdk(elements=[mock_element]):
        result = loc._call_aliyun_detect_api("b64data", "按钮")

    assert result["found"] is True
    assert result["coords"] is None


def test_call_aliyun_detect_api_lowercase_data_key() -> None:
    """响应中 element 包含 box 属性（小写）时，也应正确解析。"""
    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "key",
        "ALIYUN_ACCESS_KEY_SECRET": "secret",
    }):
        loc = ElementLocator()

    mock_element = MagicMock()
    mock_box = MagicMock()
    mock_box.x = 10
    mock_box.y = 20
    mock_box.width = 40
    mock_box.height = 20
    mock_element.box = mock_box
    mock_element.score = 0.75

    with _patch_aliyun_sdk(elements=[mock_element]):
        result = loc._call_aliyun_detect_api("b64data", "按钮")

    assert result["found"] is True
    assert result["coords"] is not None


# ---------------------------------------------------------------------------
# _locate_by_qwen_vl — 策略 2 覆盖
# ---------------------------------------------------------------------------


def test_locate_by_qwen_vl_success(locator: ElementLocator, black_screenshot: np.ndarray) -> None:
    """Qwen-VL API 返回 found=True 且 coords 非 None 时，应返回 ElementResult。
    实现以中心点 (100, 200) 构造 40×40 的默认 bbox，即 (80, 180, 40, 40)。
    """
    api_response = {"found": True, "coords": [100, 200], "confidence": 0.88}
    with patch.object(locator, "_call_qwen_vl_api", return_value=api_response):
        result = locator._locate_by_qwen_vl(black_screenshot, "安装按钮")

    assert result is not None
    assert result.strategy == "qwen_vl"
    # bbox is centered at (100, 200) with default 40×40 size: (cx-20, cy-20, 40, 40)
    assert result.bbox == (80, 180, 40, 40)
    assert abs(result.confidence - 0.88) < 1e-6


def test_locate_by_qwen_vl_found_true_coords_none_returns_none(
    locator: ElementLocator, black_screenshot: np.ndarray
) -> None:
    """Qwen-VL 返回 found=True 但 coords=None 时，必须返回 None 触发降级。"""
    api_response = {"found": True, "coords": None}
    with patch.object(locator, "_call_qwen_vl_api", return_value=api_response):
        result = locator._locate_by_qwen_vl(black_screenshot, "安装按钮")
    assert result is None


def test_locate_by_qwen_vl_found_false_returns_none(
    locator: ElementLocator, black_screenshot: np.ndarray
) -> None:
    """Qwen-VL 返回 found=False 时，应返回 None。"""
    api_response = {"found": False, "coords": None}
    with patch.object(locator, "_call_qwen_vl_api", return_value=api_response):
        result = locator._locate_by_qwen_vl(black_screenshot, "按钮")
    assert result is None


def test_locate_by_qwen_vl_api_exception_returns_none(
    locator: ElementLocator, black_screenshot: np.ndarray
) -> None:
    """Qwen-VL API 抛出异常时，应捕获并返回 None。"""
    with patch.object(locator, "_call_qwen_vl_api", side_effect=RuntimeError("timeout")):
        result = locator._locate_by_qwen_vl(black_screenshot, "按钮")
    assert result is None


def test_locate_by_qwen_vl_encode_failure_returns_none(
    locator: ElementLocator, black_screenshot: np.ndarray
) -> None:
    """cv2.imencode 失败时，应返回 None。"""
    with patch("cv2.imencode", return_value=(False, None)):
        result = locator._locate_by_qwen_vl(black_screenshot, "按钮")
    assert result is None


# ---------------------------------------------------------------------------
# _call_qwen_vl_api — 响应解析覆盖
# ---------------------------------------------------------------------------


def _make_openai_response(content: str) -> MagicMock:
    """构造模拟 OpenAI 兼容接口的响应对象。"""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    return mock_response


def test_call_qwen_vl_api_missing_api_key_raises() -> None:
    """未配置 DASHSCOPE_API_KEY 时，应抛出 RuntimeError。"""
    import os
    env = {k: v for k, v in os.environ.items() if k != "DASHSCOPE_API_KEY"}
    env["ALIYUN_ACCESS_KEY_ID"] = "key"
    env["ALIYUN_ACCESS_KEY_SECRET"] = "secret"

    with patch.dict("os.environ", env, clear=True):
        loc = ElementLocator()
        with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
            loc._call_qwen_vl_api("b64data", "按钮")


def test_call_qwen_vl_api_non_200_raises() -> None:
    """API 调用抛出异常时，应向上传播 RuntimeError。"""
    from openai import APIStatusError
    import httpx

    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "key",
        "ALIYUN_ACCESS_KEY_SECRET": "secret",
        "DASHSCOPE_API_KEY": "test_key",
    }):
        loc = ElementLocator()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("API error 429")
        with patch("openai.OpenAI", return_value=mock_client):
            with pytest.raises(RuntimeError):
                loc._call_qwen_vl_api("b64data", "按钮")


def test_call_qwen_vl_api_parses_json_response() -> None:
    """API 返回合法 JSON 时，应正确解析并返回字典。"""
    payload = '{"found": true, "coords": [150, 250], "confidence": 0.95}'
    mock_response = _make_openai_response(payload)

    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "key",
        "ALIYUN_ACCESS_KEY_SECRET": "secret",
        "DASHSCOPE_API_KEY": "test_key",
    }):
        loc = ElementLocator()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        with patch("openai.OpenAI", return_value=mock_client):
            result = loc._call_qwen_vl_api("b64data", "按钮")

    assert result["found"] is True
    assert result["coords"] == [150, 250]


def test_call_qwen_vl_api_strips_markdown_code_block() -> None:
    """模型输出包裹在 markdown 代码块中时，应正确剥离并解析 JSON。"""
    payload = '```json\n{"found": true, "coords": [50, 60]}\n```'
    mock_response = _make_openai_response(payload)

    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "key",
        "ALIYUN_ACCESS_KEY_SECRET": "secret",
        "DASHSCOPE_API_KEY": "test_key",
    }):
        loc = ElementLocator()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        with patch("openai.OpenAI", return_value=mock_client):
            result = loc._call_qwen_vl_api("b64data", "按钮")

    assert result["found"] is True
    assert result["coords"] == [50, 60]


def test_call_qwen_vl_api_found_false_response() -> None:
    """模型返回 found=false 时，应正确解析。"""
    payload = '{"found": false, "coords": null}'
    mock_response = _make_openai_response(payload)

    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "key",
        "ALIYUN_ACCESS_KEY_SECRET": "secret",
        "DASHSCOPE_API_KEY": "test_key",
    }):
        loc = ElementLocator()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        with patch("openai.OpenAI", return_value=mock_client):
            result = loc._call_qwen_vl_api("b64data", "按钮")

    assert result["found"] is False


def test_call_qwen_vl_api_invalid_json_raises() -> None:
    """模型输出无法解析为 JSON 时，应抛出 RuntimeError。"""
    mock_response = _make_openai_response("这不是JSON")

    with patch.dict("os.environ", {
        "ALIYUN_ACCESS_KEY_ID": "key",
        "ALIYUN_ACCESS_KEY_SECRET": "secret",
        "DASHSCOPE_API_KEY": "test_key",
    }):
        loc = ElementLocator()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        with patch("openai.OpenAI", return_value=mock_client):
            with pytest.raises(RuntimeError, match="JSON 解析失败"):
                loc._call_qwen_vl_api("b64data", "按钮")

