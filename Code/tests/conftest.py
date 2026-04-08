"""共享 pytest fixture，供所有测试模块使用。

提供对外部依赖的 mock：DashScope API、mss 截图、pyautogui 鼠标键盘操作、pyperclip 剪贴板。
"""
from __future__ import annotations

from typing import Generator
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, settings

# Override max_examples globally so property tests run faster.
# Individual @settings(max_examples=...) decorators are superseded by this profile
# when it is loaded as the default.
settings.register_profile("fast", max_examples=20, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("fast")

import numpy as np
import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Redirect tmp_path to a local directory to avoid Windows system temp permission issues."""
    import pathlib
    local_tmp = pathlib.Path(__file__).parent / "tmp"
    local_tmp.mkdir(exist_ok=True)
    config.option.basetemp = local_tmp


@pytest.fixture
def mock_dashscope() -> Generator[dict[str, MagicMock], None, None]:
    """Mock DashScope API 调用，返回成功的默认响应。

    mock `dashscope.Generation.call`（文本模型）和
    OpenAI 兼容接口（视觉模型，element_locator 使用 openai.OpenAI）。

    Yields:
        包含两个 mock 对象的字典：
        - "generation": Generation.call 的 MagicMock
        - "multimodal": openai.OpenAI 实例的 chat.completions.create MagicMock
    """
    generation_response = MagicMock()
    generation_response.status_code = 200
    generation_response.output.choices = [
        MagicMock(message=MagicMock(content="mock response", tool_calls=None))
    ]

    # OpenAI-compatible response format used by element_locator._call_qwen_vl_api
    multimodal_response = MagicMock()
    multimodal_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"found": true, "coords": [100, 200], "confidence": 0.9}'
            )
        )
    ]

    mock_openai_client = MagicMock()
    mock_openai_client.chat.completions.create.return_value = multimodal_response

    with (
        patch("dashscope.Generation.call", return_value=generation_response) as mock_gen,
        patch("openai.OpenAI", return_value=mock_openai_client) as mock_mm,
    ):
        yield {"generation": mock_gen, "multimodal": mock_mm}


@pytest.fixture
def mock_mss() -> Generator[MagicMock, None, None]:
    """Mock mss.mss() 截图，返回固定尺寸的黑色 numpy 数组。

    截图尺寸为 1080x1920x4（高×宽×通道，BGRA），全部像素值为 0（黑色）。
    mss 实际返回 BGRA 4 通道，screen_capturer 通过 [:, :, :3] 截取 BGR 3 通道。

    Yields:
        mss.mss 上下文管理器的 MagicMock 实例。
    """
    # mss 实际返回 BGRA 4 通道；screen_capturer 用 [:, :, :3] 取 BGR
    black_frame_bgra = np.zeros((1080, 1920, 4), dtype=np.uint8)

    mock_screenshot = MagicMock()
    # np.array(screenshot) 调用 __array__，返回 BGRA 数组
    mock_screenshot.__array__ = MagicMock(return_value=black_frame_bgra)

    mock_mss_instance = MagicMock()
    mock_mss_instance.grab.return_value = mock_screenshot
    mock_mss_instance.monitors = [
        {"left": 0, "top": 0, "width": 1920, "height": 1080},   # 虚拟全屏（索引 0）
        {"left": 0, "top": 0, "width": 1920, "height": 1080},   # 主显示器（索引 1）
    ]
    mock_mss_instance.__enter__ = MagicMock(return_value=mock_mss_instance)
    mock_mss_instance.__exit__ = MagicMock(return_value=False)

    with patch("mss.mss", return_value=mock_mss_instance):
        yield mock_mss_instance


@pytest.fixture
def mock_pyautogui() -> Generator[dict[str, MagicMock], None, None]:
    """Mock pyautogui 的鼠标键盘操作方法，全部返回 None。

    mock 的方法：
    - `click`: 鼠标点击
    - `moveTo`: 鼠标移动
    - `hotkey`: 组合键
    - `typewrite`: 文本输入

    Yields:
        包含各 mock 方法的字典，键为方法名。
    """
    with (
        patch("pyautogui.click", return_value=None) as mock_click,
        patch("pyautogui.moveTo", return_value=None) as mock_move,
        patch("pyautogui.hotkey", return_value=None) as mock_hotkey,
        patch("pyautogui.typewrite", return_value=None) as mock_typewrite,
    ):
        yield {
            "click": mock_click,
            "moveTo": mock_move,
            "hotkey": mock_hotkey,
            "typewrite": mock_typewrite,
        }


@pytest.fixture
def mock_pyperclip() -> Generator[dict[str, MagicMock], None, None]:
    """Mock pyperclip 的剪贴板操作方法。

    mock 的方法：
    - `copy`: 写入剪贴板，返回 None
    - `paste`: 读取剪贴板，返回空字符串

    Yields:
        包含 "copy" 和 "paste" mock 对象的字典。
    """
    with (
        patch("pyperclip.copy", return_value=None) as mock_copy,
        patch("pyperclip.paste", return_value="") as mock_paste,
    ):
        yield {"copy": mock_copy, "paste": mock_paste}
