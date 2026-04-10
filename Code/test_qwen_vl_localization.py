"""独立诊断脚本：测试 Qwen-VL API 连通性并生成带红框标注的截图。

使用方式：
    python test_qwen_vl_localization.py

环境变量（必须）：
    DASHSCOPE_API_KEY   — 通义千问 API Key

依赖：
    pip install dashscope opencv-python numpy mss Pillow openai
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import ctypes
import cv2
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qwen_vl_diag")


def get_dpi_scale() -> float:
    """读取主显示器 DPI 缩放比例（150% → 1.5）。"""
    try:
        import ctypes.wintypes as _wt
        hmon = ctypes.windll.user32.MonitorFromPoint(_wt.POINT(0, 0), 2)
        sf = ctypes.c_uint(0)
        if ctypes.windll.shcore.GetScaleFactorForMonitor(hmon, ctypes.byref(sf)) == 0 and sf.value > 0:
            return sf.value / 100.0
    except Exception:
        pass
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0

# 要测试的按钮列表
BUTTON_TARGETS: list[str] = ["下一步", "我同意", "安装", "完成"]

# 输出目录
DEBUG_DIR = Path("debug")


# ---------------------------------------------------------------------------
# 截图
# ---------------------------------------------------------------------------

def capture_screen() -> np.ndarray:
    """截取全屏，返回 BGR numpy 数组（物理像素）。"""
    try:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            raw = sct.grab(monitor)
            img = np.frombuffer(raw.bgra, dtype=np.uint8).reshape(raw.height, raw.width, 4)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    except ImportError:
        pass
    from PIL import ImageGrab
    pil_img = ImageGrab.grab()
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def find_installer_window() -> tuple[int, int, int, int, int] | None:
    """枚举顶层窗口，找到安装程序窗口，返回 (left, top, width, height, hwnd)。

    使用 DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS) 获取真实物理像素边界，
    避免 DPI 缩放导致 GetWindowRect 返回逻辑坐标偏小的问题。
    """
    import ctypes.wintypes as _wt

    KEYWORDS = ["安装", "Setup", "Install", "Wizard", "向导"]
    user32 = ctypes.windll.user32
    found: list[tuple[int, int, int, int, int, str]] = []

    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if not title:
            return True
        for kw in KEYWORDS:
            if kw.lower() in title.lower():
                # 优先用 DwmGetWindowAttribute 获取真实物理像素边界
                rect = _get_physical_window_rect(hwnd)
                if rect:
                    left, top, w, h = rect
                    if w > 50 and h > 50:
                        found.append((left, top, w, h, hwnd, title))
                return True
        return True

    user32.EnumWindows(EnumProc(_cb), 0)

    if not found:
        return None

    left, top, w, h, hwnd, title = found[0]
    logger.info("找到安装窗口：%r  物理区域=(%d,%d,%d,%d) hwnd=%d", title, left, top, w, h, hwnd)
    return left, top, w, h, hwnd


def _get_physical_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """获取窗口真实物理像素内容边界（不含 DWM 阴影）。

    策略：GetWindowRect 返回逻辑坐标，乘以 DPI scale 得到物理坐标。
    不用 DwmFrameBounds，因为它包含阴影导致底部被截掉。
    """
    import ctypes.wintypes as _wt

    try:
        rect = _wt.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        lw = rect.right - rect.left
        lh = rect.bottom - rect.top
        if lw <= 0 or lh <= 0:
            return None
        scale = get_dpi_scale()
        # 逻辑坐标 → 物理坐标
        pw = int(round(lw * scale))
        ph = int(round(lh * scale))
        pleft = int(round(rect.left * scale))
        ptop = int(round(rect.top * scale))
        logger.debug("GetWindowRect×%.2f: (%d,%d,%d,%d)", scale, pleft, ptop, pw, ph)
        return pleft, ptop, pw, ph
    except Exception as exc:
        logger.debug("GetWindowRect 失败: %s", exc)
        return None


def capture_window(win_rect: tuple) -> np.ndarray:
    """用 PrintWindow 从窗口句柄截图，正确捕获 DWM 合成窗口内容。

    使用 GetWindowRect 的逻辑尺寸作为 bitmap 尺寸，再乘以 DPI scale 得到物理像素图。
    """
    left, top, w, h, hwnd = win_rect

    import ctypes.wintypes as _wt

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # 用 GetClientRect 获取客户区逻辑尺寸，乘以 scale 得到物理像素尺寸
    client_rect = _wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client_rect))
    scale = get_dpi_scale()
    bmp_w = max(w, int(round(client_rect.right * scale)))
    bmp_h = max(h, int(round(client_rect.bottom * scale)))
    logger.debug("PrintWindow bitmap: %dx%d (client logical: %dx%d × %.2f)",
                 bmp_w, bmp_h, client_rect.right, client_rect.bottom, scale)

    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, bmp_w, bmp_h)
    gdi32.SelectObject(mem_dc, bitmap)

    # PW_RENDERFULLCONTENT=2 捕获完整 DWM 内容
    if not user32.PrintWindow(hwnd, mem_dc, 2):
        user32.PrintWindow(hwnd, mem_dc, 0)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = bmp_w
    bmi.biHeight = -bmp_h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = (ctypes.c_byte * (bmp_w * bmp_h * 4))()
    gdi32.GetDIBits(mem_dc, bitmap, 0, bmp_h, buf, ctypes.byref(bmi), 0)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    img = np.frombuffer(buf, dtype=np.uint8).reshape(bmp_h, bmp_w, 4)
    result = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    logger.debug("PrintWindow result: %dx%d mean=%.1f", bmp_w, bmp_h, result.mean())
    return result


# ---------------------------------------------------------------------------
# API 调用
# ---------------------------------------------------------------------------

def call_qwen_vl(image: np.ndarray, button_text: str) -> str:
    """调用 Qwen-VL API，返回模型原始响应文本。

    image 应已缩放到逻辑分辨率，模型返回的坐标即为逻辑坐标。
    """
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置，请设置环境变量后重试。")

    h, w = image.shape[:2]
    success, buf = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("图像编码失败")
    b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

    prompt = (
        f'你是一个精准的UI元素定位模型。\n'
        f'【重要】图像尺寸严格为 {w}x{h} 像素，坐标 x 范围 0~{w-1}，y 范围 0~{h-1}，超出范围的坐标无效。\n\n'
        f'任务：在截图中找到文字包含"{button_text}"的可点击按钮控件（按钮文字可能带快捷键后缀如"(N)"）。\n'
        f'只定位按钮控件，不要匹配正文段落中的相同文字。按钮通常在窗口底部区域。\n\n'
        f'输出格式：只返回一个 JSON 对象，不要任何额外文字。\n'
        f'找到时：{{"found": true, "center": [x, y], "bbox": [x1, y1, x2, y2], "confidence": 0.95}}\n'
        f'未找到时：{{"found": false, "reason": "原因"}}\n'
        f'所有坐标必须是整数且在图像范围内（x: 0~{w-1}, y: 0~{h-1}）。'
    )

    from openai import OpenAI
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    response = client.chat.completions.create(
        model="qwen3-vl-plus",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
        temperature=0.1,
        max_tokens=512,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# 坐标解析
# ---------------------------------------------------------------------------

def parse_coordinates(response_text: str) -> tuple[dict, tuple[int, int] | None]:
    """从模型响应中提取坐标。

    Returns:
        (parsed_dict, center_xy)
        parsed_dict: 解析后的 JSON 字典（解析失败时为空字典）
        center_xy: (x, y) 中心点，未找到或解析失败时为 None
    """
    text = response_text.strip()

    # 清理 Markdown 代码块
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # 提取第一个 JSON 对象
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        logger.warning("响应中未找到 JSON 对象，原始内容：%r", response_text[:200])
        return {}, None

    try:
        parsed: dict = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("JSON 解析失败：%s，原始内容：%r", exc, response_text[:200])
        return {}, None

    if not parsed.get("found"):
        return parsed, None

    # 优先取 center
    center = parsed.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        try:
            return parsed, (int(center[0]), int(center[1]))
        except (TypeError, ValueError):
            pass

    # 从 bbox 推算中心
    bbox = parsed.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            return parsed, ((x1 + x2) // 2, (y1 + y2) // 2)
        except (TypeError, ValueError):
            pass

    return parsed, None


# ---------------------------------------------------------------------------
# 绘制标注
# ---------------------------------------------------------------------------

def draw_boxes(
    image: np.ndarray,
    boxes: list[dict],
) -> np.ndarray:
    """在图像副本上绘制红色矩形框和标签。

    Args:
        image: BGR numpy 数组（原图，不修改）。
        boxes: 每项包含 label、center (x,y)、bbox [x1,y1,x2,y2]（可选）、confidence（可选）。

    Returns:
        绘制了标注的图像副本。
    """
    output = image.copy()
    h, w = output.shape[:2]
    color = (0, 0, 255)  # 红色 BGR

    for box in boxes:
        label: str = box.get("label", "")
        confidence: float = float(box.get("confidence", 0.0))
        center = box.get("center")
        bbox = box.get("bbox")

        # 确定矩形区域
        if bbox and len(bbox) == 4:
            x1, y1, x2, y2 = [int(v) for v in bbox]
        elif center:
            cx, cy = int(center[0]), int(center[1])
            half = 20
            x1, y1, x2, y2 = cx - half, cy - half, cx + half, cy + half
        else:
            continue

        # 钳制到图像范围
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w - 1, x2), min(h - 1, y2)

        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)

        # 标签文字
        text = f"{label} {confidence:.2f}" if confidence > 0 else label
        font = cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), baseline = cv2.getTextSize(text, font, 0.5, 1)
        ty = y1 - 4 if y1 - th - 4 >= 0 else y2 + th + 4
        cv2.rectangle(output, (x1, ty - th - 2), (x1 + tw + 4, ty + baseline), color, cv2.FILLED)
        cv2.putText(output, text, (x1 + 2, ty), font, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    return output


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    scale = get_dpi_scale()
    logger.info("=== Qwen-VL 定位诊断脚本启动 ===")
    logger.info("DPI 缩放比例：%.2f", scale)

    # 查找安装窗口，最多等待 30 秒
    win_rect = None
    logger.info("等待安装窗口出现（最多 30 秒）...请现在打开安装包")
    for _ in range(30):
        win_rect = find_installer_window()
        if win_rect is not None:
            break
        time.sleep(1)

    if win_rect is None:
        logger.warning("未找到安装窗口，回退到全屏截图")
        screenshot_phys = capture_screen()
        win_offset = (0, 0)
    else:
        left, top, w, h, hwnd = win_rect
        screenshot_phys = capture_window(win_rect)
        win_offset = (left, top)
        logger.info("使用窗口截图：物理尺寸 %dx%d，偏移 (%d,%d)", w, h, left, top)

    ph, pw = screenshot_phys.shape[:2]
    logger.info("截图尺寸（物理）：%dx%d", pw, ph)
    logger.info("目标按钮：%s", BUTTON_TARGETS)
    logger.info("截图将保存到：%s/", DEBUG_DIR)

    # 保存原始窗口截图供参考
    raw_path = DEBUG_DIR / f"window_raw_{ts}.png"
    cv2.imwrite(str(raw_path), screenshot_phys)
    logger.info("原始窗口截图已保存：%s", raw_path)

    # 所有按钮的标注结果绘制在同一张图上
    annotated_combined = screenshot_phys.copy()

    # 发给模型的图：resize 到标准宽度 1280px，避免模型内部缩放导致坐标偏移
    TARGET_W = 1280
    if pw != TARGET_W:
        api_scale = TARGET_W / pw
        api_w = TARGET_W
        api_h = int(round(ph * api_scale))
        screenshot_for_api = cv2.resize(screenshot_phys, (api_w, api_h), interpolation=cv2.INTER_CUBIC)
        logger.info("发给模型的图：resize 到 %dx%d (scale=%.3f)", api_w, api_h, api_scale)
    else:
        screenshot_for_api = screenshot_phys
        api_scale = 1.0
        logger.info("发给模型的图尺寸：%dx%d（原始）", pw, ph)

    for button_text in BUTTON_TARGETS:
        logger.info("--- 测试按钮：%r ---", button_text)

        # 方法1：pywinauto 控件定位（精确，不依赖视觉）
        try:
            from pywinauto import Application
            app = Application(backend='win32').connect(title_re='.*安装.*', timeout=2)
            win = app.top_window()
            for ctrl in win.descendants():
                try:
                    txt = ctrl.window_text().strip()
                    if button_text in txt and ctrl.friendly_class_name() == 'Button':
                        rect = ctrl.rectangle()
                        cx = (rect.left + rect.right) // 2
                        cy = (rect.top + rect.bottom) // 2
                        logger.info(
                            "pywinauto 定位 %r：屏幕物理=(%d,%d) rect=%s",
                            button_text, cx, cy, rect,
                        )
                        # 在截图上标出 pywinauto 坐标（转换为窗口内坐标）
                        wx_pw = cx - win_offset[0]
                        wy_pw = cy - win_offset[1]
                        if 0 <= wx_pw < pw and 0 <= wy_pw < ph:
                            cv2.circle(annotated_combined, (wx_pw, wy_pw), 8, (0, 255, 0), -1)
                            cv2.putText(annotated_combined, f"PW:{button_text}",
                                       (wx_pw + 10, wy_pw), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                        break
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("pywinauto 定位失败（不影响流程）: %s", exc)

        # 调用 API（传放大后的图）
        try:
            raw_text = call_qwen_vl(screenshot_for_api, button_text)
            logger.info("API 原始响应：%s", raw_text[:300])
        except RuntimeError as exc:
            logger.error("API 调用失败：%s", exc)
            sys.exit(1)
        except Exception as exc:
            logger.error("API 调用异常：%s", exc)
            continue

        # 解析坐标（相对于窗口截图的物理坐标）
        parsed, center_in_window = parse_coordinates(raw_text)
        if not parsed.get("found"):
            logger.warning("按钮 %r 未找到：%s", button_text, parsed.get("reason", "found=false"))
            continue

        if center_in_window is None:
            logger.warning("按钮 %r：found=true 但坐标为 None", button_text)
            continue

        wx, wy = center_in_window
        confidence = float(parsed.get("confidence", 0.0))

        # 模型坐标基于 api_scale 放大图，缩回物理窗口坐标，并钳制到窗口范围
        wx = max(0, min(int(round(wx / api_scale)), pw - 1))
        wy = max(0, min(int(round(wy / api_scale)), ph - 1))

        # 窗口内坐标 → 屏幕绝对物理坐标
        screen_x = wx + win_offset[0]
        screen_y = wy + win_offset[1]
        logger.info(
            "按钮 %r：窗口内=(%d,%d) → 屏幕物理=(%d,%d)，confidence=%.3f",
            button_text, wx, wy, screen_x, screen_y, confidence,
        )

        # bbox 处理（缩回物理坐标并钳制）
        raw_bbox = parsed.get("bbox")
        phys_bbox = None
        if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
            x1 = max(0, min(int(round(raw_bbox[0] / api_scale)), pw - 1))
            y1 = max(0, min(int(round(raw_bbox[1] / api_scale)), ph - 1))
            x2 = max(0, min(int(round(raw_bbox[2] / api_scale)), pw - 1))
            y2 = max(0, min(int(round(raw_bbox[3] / api_scale)), ph - 1))
            phys_bbox = [x1, y1, x2, y2]

        # 在合并图上绘制
        box_info = {"label": button_text, "center": [wx, wy], "bbox": phys_bbox, "confidence": confidence}
        annotated_combined = draw_boxes(annotated_combined, [box_info])

        # 同时保存单按钮截图
        single = draw_boxes(screenshot_phys, [box_info])
        safe_name = button_text.replace("/", "_").replace("\\", "_")
        out_path = DEBUG_DIR / f"qwen_{safe_name}_{ts}.png"
        cv2.imwrite(str(out_path), single)
        logger.info("单按钮截图已保存：%s", out_path)

        time.sleep(0.5)

    # 保存合并标注图
    combined_path = DEBUG_DIR / f"qwen_all_{ts}.png"
    cv2.imwrite(str(combined_path), annotated_combined)
    logger.info("=== 诊断完成。合并标注图：%s ===", combined_path)


if __name__ == "__main__":
    main()
