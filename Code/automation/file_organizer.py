"""
automation.file_organizer — 真实文件整理执行器。

按扩展名将源目录中的文件移动到目标目录的分类子目录中，
通过 progress_callback 实时上报进度。
支持 os_only（纯 OS 移动）和 vision_first（视觉识别优先 + OS 兜底）两种模式。
"""
from __future__ import annotations

import logging
import shutil
import threading
import tkinter
import tkinter.messagebox
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import yaml

if TYPE_CHECKING:
    from automation.object_detector import DetectionCache
    from automation.screen_overlay import ScreenOverlay

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"
_VALID_ORGANIZE_MODES = ["vision_first", "os_only"]
_VALID_ORGANIZE_PATHS = ["screenshot_path", "explorer_path"]

# FILE_CATEGORY_MAP: 扩展名 → (一级目录, 二级子目录)
# 整理后结构示例：Documents/PDF/report.pdf、Images/PNG/photo.png
FILE_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    # 图片
    ".jpg": ("Images", "JPG"), ".jpeg": ("Images", "JPG"),
    ".png": ("Images", "PNG"), ".gif": ("Images", "GIF"),
    ".bmp": ("Images", "BMP"), ".webp": ("Images", "WebP"),
    ".svg": ("Images", "SVG"), ".ico": ("Images", "ICO"),
    ".tiff": ("Images", "TIFF"), ".tif": ("Images", "TIFF"),
    ".heic": ("Images", "HEIC"), ".raw": ("Images", "RAW"),
    # 视频
    ".mp4": ("Videos", "MP4"), ".avi": ("Videos", "AVI"),
    ".mkv": ("Videos", "MKV"), ".mov": ("Videos", "MOV"),
    ".wmv": ("Videos", "WMV"), ".flv": ("Videos", "FLV"),
    ".webm": ("Videos", "WebM"), ".m4v": ("Videos", "M4V"),
    # 音频
    ".mp3": ("Audio", "MP3"), ".wav": ("Audio", "WAV"),
    ".flac": ("Audio", "FLAC"), ".aac": ("Audio", "AAC"),
    ".ogg": ("Audio", "OGG"), ".wma": ("Audio", "WMA"),
    ".m4a": ("Audio", "M4A"),
    # 文档 — 每种格式独立子目录
    ".pdf": ("Documents", "PDF"),
    ".doc": ("Documents", "Word"), ".docx": ("Documents", "Word"),
    ".xls": ("Documents", "Excel"), ".xlsx": ("Documents", "Excel"),
    ".ppt": ("Documents", "PPT"), ".pptx": ("Documents", "PPT"),
    ".txt": ("Documents", "TXT"),
    ".md": ("Documents", "Markdown"),
    ".rtf": ("Documents", "RTF"),
    ".odt": ("Documents", "Word"), ".ods": ("Documents", "Excel"),
    ".odp": ("Documents", "PPT"),
    ".csv": ("Documents", "CSV"),
    ".epub": ("Documents", "eBook"),
    # 压缩包
    ".zip": ("Archives", "ZIP"), ".rar": ("Archives", "RAR"),
    ".7z": ("Archives", "7Z"), ".tar": ("Archives", "TAR"),
    ".gz": ("Archives", "GZ"), ".bz2": ("Archives", "BZ2"),
    ".xz": ("Archives", "XZ"), ".tgz": ("Archives", "TGZ"),
    ".cab": ("Archives", "CAB"), ".iso": ("Archives", "ISO"),
    # 可执行 / 安装包
    ".exe": ("Programs", "EXE"), ".msi": ("Programs", "MSI"),
    ".dmg": ("Programs", "DMG"), ".apk": ("Programs", "APK"),
    ".deb": ("Programs", "DEB"), ".rpm": ("Programs", "RPM"),
    # 代码
    ".py": ("Code", "Python"), ".js": ("Code", "JavaScript"),
    ".ts": ("Code", "TypeScript"), ".java": ("Code", "Java"),
    ".cpp": ("Code", "C++"), ".c": ("Code", "C"), ".h": ("Code", "C"),
    ".cs": ("Code", "CSharp"), ".go": ("Code", "Go"),
    ".rs": ("Code", "Rust"), ".rb": ("Code", "Ruby"),
    ".php": ("Code", "PHP"), ".html": ("Code", "Web"),
    ".css": ("Code", "Web"), ".json": ("Code", "Config"),
    ".xml": ("Code", "Config"), ".yaml": ("Code", "Config"),
    ".yml": ("Code", "Config"), ".sh": ("Code", "Shell"),
    ".bat": ("Code", "Shell"), ".ps1": ("Code", "Shell"),
    ".sql": ("Code", "SQL"),
}

_FILE_TYPE_CATEGORY_MAP: dict[str, tuple[str, str] | None] = {
    "PDF":         ("Documents", "PDF"),
    "Word":        ("Documents", "Word"),
    "Excel":       ("Documents", "Excel"),
    "PowerPoint":  ("Documents", "PPT"),
    "Image":       ("Images", "Other"),
    "Video":       ("Videos", "Other"),
    "Audio":       ("Audio", "Other"),
    "Archive":     ("Archives", "Other"),
    "Code":        ("Code", "Other"),
    "Program":     ("Programs", "Other"),
    "Folder":      None,
    "Other":       ("Others", "Other"),
}


def _get_category_for_item(file: Path, file_type: str) -> tuple[str, str] | None:
    """扩展名优先 + file_type 兜底分类，返回 (一级目录, 二级子目录)。

    Returns:
        (parent, sub) 元组；返回 None 表示跳过（如 Folder 类型）。
    """
    ext = file.suffix.lower()
    if ext in FILE_CATEGORY_MAP:
        return FILE_CATEGORY_MAP[ext]
    if file_type not in _FILE_TYPE_CATEGORY_MAP:
        return ("Others", "Other")
    result = _FILE_TYPE_CATEGORY_MAP[file_type]
    return result


def _load_organize_mode() -> str:
    """从 config/settings.yaml 读取 file_organize_mode 字段。

    Returns:
        "vision_first" 或 "os_only"。

    Raises:
        ValueError: 字段值不在合法列表中时抛出，消息包含非法值和合法值列表。
    """
    try:
        with _SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("读取 settings.yaml 失败，使用默认 file_organize_mode='os_only': %s", exc)
        return "os_only"

    mode = data.get("file_organize_mode")
    if mode is None:
        logger.warning(
            "settings.yaml 中缺少 file_organize_mode 字段，使用默认值 'os_only'"
        )
        return "os_only"

    if mode not in _VALID_ORGANIZE_MODES:
        raise ValueError(
            f"非法的 file_organize_mode 值: {mode!r}，合法值为 {_VALID_ORGANIZE_MODES}"
        )

    return mode


def _load_organize_path() -> str:
    """从 config/settings.yaml 读取 organize_path 字段。

    Returns:
        "screenshot_path" 或 "explorer_path"。

    Raises:
        ValueError: 字段值不在合法列表中时抛出，消息包含非法值和合法值列表。
    """
    try:
        with _SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("读取 settings.yaml 失败，使用默认 organize_path='screenshot_path': %s", exc)
        return "screenshot_path"

    path_val = data.get("organize_path")
    if path_val is None:
        logger.warning(
            "settings.yaml 中缺少 organize_path 字段，使用默认值 'screenshot_path'"
        )
        return "screenshot_path"

    if path_val not in _VALID_ORGANIZE_PATHS:
        raise ValueError(
            f"非法的 organize_path 值: {path_val!r}，合法值为 {_VALID_ORGANIZE_PATHS}"
        )

    return path_val


def _show_fallback_dialog(failed_files: list[Path]) -> bool:
    """在后台线程中显示 tkinter 弹窗，询问是否对失败文件执行 OS 移动。

    Args:
        failed_files: 视觉识别失败的文件路径列表。

    Returns:
        True 表示用户选择执行 OS 移动，False 表示跳过。
        超时（300 秒）或 tkinter 初始化失败时默认返回 True。
    """
    result_ready = threading.Event()
    user_choice: list[bool] = [True]  # default: execute OS move

    def _run_dialog() -> None:
        try:
            root = tkinter.Tk()
            root.withdraw()

            # Build file list message (max 10 entries)
            names = [f.name for f in failed_files]
            if len(names) <= 10:
                file_list = "\n".join(names)
            else:
                shown = "\n".join(names[:10])
                remaining = len(names) - 10
                file_list = f"{shown}\n...等 {remaining} 个文件"

            message = (
                f"以下文件视觉识别失败，是否使用 OS 方式移动？\n\n{file_list}"
            )

            answer = tkinter.messagebox.askyesno(
                title="视觉识别失败 — 是否使用 OS 兜底？",
                message=message,
                parent=root,
            )
            user_choice[0] = bool(answer)
            root.destroy()
        except Exception as exc:
            logger.warning("tkinter 弹窗初始化失败，默认执行 OS 移动: %s", exc)
            user_choice[0] = True
        finally:
            result_ready.set()

    t = threading.Thread(target=_run_dialog, daemon=True)
    t.start()

    if not result_ready.wait(timeout=300):
        logger.warning("等待用户响应超时（300 秒），默认执行 OS 移动")
        return True

    return user_choice[0]


def _load_move_confidence_threshold() -> float:
    """从 config/settings.yaml 读取 vision.move_confidence_threshold。

    Returns:
        置信度门控阈值，范围 [0.0, 1.0]。
        缺失或读取失败时返回 0.0（关闭门控，等同旧行为）。
    """
    try:
        with _SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        value = data.get("vision", {}).get("move_confidence_threshold")
        if value is not None:
            threshold = float(value)
            return max(0.0, min(1.0, threshold))
    except Exception as exc:
        logger.warning("读取 move_confidence_threshold 失败，使用默认值 0.0: %s", exc)
    return 0.0


def _show_low_confidence_dialog(low_conf_files: list[tuple[Path, float]]) -> bool:
    """弹窗询问用户是否移动低置信度文件。

    Args:
        low_conf_files: (文件路径, 置信度) 元组列表。

    Returns:
        True 表示用户选择继续移动，False 表示跳过这些文件。
        超时（120 秒）或 tkinter 初始化失败时默认返回 False（跳过，保护文件）。
    """
    result_ready = threading.Event()
    user_choice: list[bool] = [False]  # 默认跳过，保护文件安全

    def _run_dialog() -> None:
        try:
            root = tkinter.Tk()
            root.withdraw()

            lines = []
            for path, conf in low_conf_files[:10]:
                lines.append(f"  {path.name}  (置信度 {conf:.2f})")
            if len(low_conf_files) > 10:
                lines.append(f"  ...等 {len(low_conf_files) - 10} 个文件")

            message = (
                "以下文件的视觉识别置信度较低（红色框），\n"
                "系统不确定是否正确识别，是否仍然移动？\n\n"
                + "\n".join(lines)
                + "\n\n选择「否」将跳过这些文件，保持原位。"
            )

            answer = tkinter.messagebox.askyesno(
                title="低置信度文件 — 是否继续移动？",
                message=message,
                parent=root,
                default=tkinter.messagebox.NO,  # 默认选"否"
            )
            user_choice[0] = bool(answer)
            root.destroy()
        except Exception as exc:
            logger.warning("低置信度弹窗初始化失败，默认跳过: %s", exc)
            user_choice[0] = False
        finally:
            result_ready.set()

    t = threading.Thread(target=_run_dialog, daemon=True)
    t.start()

    if not result_ready.wait(timeout=120):
        logger.warning("等待用户响应超时（120 秒），默认跳过低置信度文件")
        return False

    return user_choice[0]


def run_file_organizer(
    source_dir: str | Path,
    target_dir: str | Path,
    progress_callback: Callable[[str, int], None],
    stop_event: threading.Event,
    file_filters: list[str] | None = None,
    detection_cache: DetectionCache | None = None,
    screen_overlay: ScreenOverlay | None = None,
    confirm_callback: Callable[[str], bool] | None = None,
) -> None:
    """执行真实文件整理任务。

    根据 settings.yaml 中的 file_organize_mode 选择执行模式：
    - os_only: 使用 shutil.move 按扩展名分类移动文件
    - vision_first: 打开 Explorer，用 pywinauto 定位文件坐标，
                    识别框显示在 Windows 屏幕叠加层上，Gradio 浏览器最小化

    Args:
        source_dir: 源目录路径。
        target_dir: 目标目录路径（不存在时自动创建）。整理结果放在此目录下。
        progress_callback: 签名 (step_description: str, percent: int) -> None。
        stop_event: 外部停止信号。
        file_filters: 可选扩展名过滤列表。
        detection_cache: 可选 DetectionCache，供 Gradio 预览叠加识别框。
        screen_overlay: 可选 ScreenOverlay，在 Windows 屏幕上直接绘制识别框。
        confirm_callback: 可选确认回调，签名 (message: str) -> bool。
            用于替代 tkinter 弹窗，向前端推送确认请求并等待用户响应。
            为 None 时回退到 tkinter 弹窗。

    Raises:
        FileNotFoundError: source_dir 不存在时抛出。
    """
    source = Path(source_dir)
    target = Path(target_dir)

    if not source.exists():
        raise FileNotFoundError(f"源目录不存在：{source_dir}")

    # Skip mkdir for drive roots (e.g. D:\) which already exist on Windows
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)

    # Normalize file_filters: ensure each starts with "."
    normalized_filters: list[str] = []
    if file_filters:
        for f in file_filters:
            f = f.lower()
            if not f.startswith("."):
                f = "." + f
            normalized_filters.append(f)

    # Scan files (non-recursive)
    all_files = [p for p in source.iterdir() if p.is_file()]
    if normalized_filters:
        files = [p for p in all_files if p.suffix.lower() in normalized_filters]
    else:
        files = all_files

    total = len(files)
    if total == 0:
        progress_callback("无匹配文件，任务完成", 100)
        return

    organize_mode = _load_organize_mode()

    # ------------------------------------------------------------------ #
    # os_only branch — original logic completely unchanged                #
    # ------------------------------------------------------------------ #
    if organize_mode == "os_only":
        for i, file in enumerate(files):
            if stop_event.is_set():
                logger.info("文件整理任务收到停止信号，已中止（文件 %d/%d）", i, total)
                return

            ext = file.suffix.lower()
            cat = FILE_CATEGORY_MAP.get(ext, ("Others", "Other"))
            parent_dir, sub_dir = cat
            dest_dir = target / "Agent-Organized" / parent_dir / sub_dir
            dest_dir.mkdir(parents=True, exist_ok=True)

            try:
                dest_name = file.name
                dest_path = dest_dir / dest_name
                if dest_path.exists():
                    stem = file.stem
                    suffix = file.suffix
                    n = 1
                    while (dest_dir / f"{stem}_{n}{suffix}").exists():
                        n += 1
                    dest_name = f"{stem}_{n}{suffix}"
                    logger.info("重命名文件：%s → %s（目标已存在）", file.name, dest_name)
                shutil.move(str(file), str(dest_dir / dest_name))
                logger.info("移动文件：%s → %s/%s/", dest_name, parent_dir, sub_dir)
            except Exception as exc:
                logger.warning("移动文件失败，跳过：%s，原因：%s", file.name, exc)
                continue

            percent = int((i + 1) / total * 100)
            progress_callback(f"移动 {file.name} → {parent_dir}/{sub_dir}/", percent)

        return

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # vision_first branch                                                 #
    # ------------------------------------------------------------------ #
    # 策略：不打开任何 Explorer 窗口（避免遮挡 GUI 界面），
    # 尝试连接已有的 Explorer 进程定位文件坐标，
    # 无论是否找到坐标都用 shutil 可靠移动文件。
    # 识别到坐标时写入 DetectionCache 供预览画面显示识别框。

    from pywinauto.application import Application  # noqa: PLC0415
    from execution.action_engine import ActionEngine  # noqa: PLC0415

    # 新增：读取 organize_path，决定截图方式
    organize_path = _load_organize_path()

    # 新增：执行 Qwen-VL 识别（失败时 vl_map 为空，后续逐文件循环直接走 vision_os）
    from automation.qwen_vl_recognizer import QwenVLRecognizer, QwenVLAPIError, VisionFileItem  # noqa: PLC0415
    recognizer = QwenVLRecognizer(detection_cache=detection_cache)
    vl_map: dict[str, VisionFileItem] = {}

    try:
        if organize_path == "explorer_path":
            # explorer_path 模式：打开 Explorer 窗口，等待出现后对窗口区域截图
            _vl_screenshot: np.ndarray | None = None
            try:
                import subprocess as _sp  # noqa: PLC0415
                import time as _t  # noqa: PLC0415
                from perception.screen_capturer import ScreenCapturer  # noqa: PLC0415
                _sp.Popen(f'explorer.exe "{source}"', shell=True)  # noqa: S602
                _t.sleep(2.0)  # 等待 Explorer 打开并渲染完成

                # 尝试用 pywinauto 获取 Explorer 窗口的精确屏幕区域
                _exp_rect = None
                try:
                    _exp_app = Application(backend="uia").connect(
                        path="explorer.exe",
                        title_re=f".*{source.name}.*",
                        timeout=3,
                    )
                    _exp_win = _exp_app.top_window()
                    _r = _exp_win.rectangle()
                    _exp_rect = (_r.left, _r.top, _r.right - _r.left, _r.bottom - _r.top)
                    logger.info(
                        "vision_first: Explorer 窗口区域 left=%d top=%d w=%d h=%d",
                        *_exp_rect,
                    )
                except Exception as _rect_exc:
                    logger.warning("vision_first: 获取 Explorer 窗口区域失败，改用全屏: %s", _rect_exc)

                _capturer2 = ScreenCapturer()
                if _exp_rect is not None:
                    # 截取 Explorer 窗口精确区域
                    lx, ly, lw, lh = _exp_rect
                    _vl_screenshot = _capturer2.capture_region_abs(lx, ly, lw, lh)
                else:
                    _vl_screenshot = _capturer2.capture_full()
                logger.info("vision_first: explorer_path 截图完成 shape=%s", _vl_screenshot.shape)
            except Exception as _exp_exc:
                logger.warning("vision_first: explorer_path 截图失败，跳过 Qwen-VL: %s", _exp_exc)
                _vl_screenshot = None
        else:
            # screenshot_path 模式：全屏截图
            try:
                from perception.screen_capturer import ScreenCapturer  # noqa: PLC0415
                _capturer = ScreenCapturer()
                _vl_screenshot = _capturer.capture_full()
            except Exception as _cap_exc:
                logger.warning("vision_first: 截图失败，跳过 Qwen-VL: %s", _cap_exc)
                _vl_screenshot = None

        if _vl_screenshot is not None:
            vl_items = recognizer.recognize_file_icons(_vl_screenshot)
            vl_map = {item.name.lower(): item for item in vl_items if item.name}
            logger.info("vision_first: Qwen-VL 识别 %d 个文件项，vl_map 大小=%d", len(vl_items), len(vl_map))
    except QwenVLAPIError as e:
        logger.error("vision_first: Qwen-VL API 失败，降级到 vision_os 流程: %s", e)
        # vl_map 保持为空，后续所有文件直接走现有 pywinauto 逻辑

    # 读取置信度门控阈值（0.0 = 关闭门控）
    move_conf_threshold = _load_move_confidence_threshold()

    # 主动打开 Explorer 并导航到源目录
    explorer_win = None
    try:
        import subprocess  # noqa: PLC0415
        subprocess.Popen(f'explorer.exe "{source}"', shell=True)  # noqa: S602
        # 等待 Explorer 窗口出现（最多 5 秒）
        import time as _time  # noqa: PLC0415
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline:
            try:
                explorer_app = Application(backend="uia").connect(
                    path="explorer.exe",
                    title_re=f".*{source.name}.*",
                    timeout=1,
                )
                explorer_win = explorer_app.top_window()
                logger.info("vision_first: 已打开并连接 Explorer 窗口 '%s'", source.name)
                break
            except Exception:
                _time.sleep(0.5)
        if explorer_win is None:
            logger.warning("vision_first: Explorer 窗口未在 5 秒内出现，将跳过坐标定位")
    except Exception as exc:
        logger.warning("vision_first: 打开 Explorer 失败: %s，将跳过坐标定位", exc)

    vision_processed = 0       # 成功移动的文件数
    files_handled = 0          # 已处理（移动+拦截+失败）的文件数，用于进度计算
    failed_files: list[Path] = []
    # 低置信度文件列表：(文件路径, 置信度)，门控开启时收集，最后统一弹窗确认
    low_conf_files: list[tuple[Path, float]] = []

    for file in files:
        if stop_event.is_set():
            logger.info("vision_first: 收到停止信号，中止")
            return

        # 新增：vision_vl 匹配（大小写不敏感，支持模糊匹配兜底）
        vl_item = vl_map.get(file.name.lower())
        # 精确匹配失败时，尝试去扩展名的模糊匹配（应对 OCR 识别偏差）
        if vl_item is None and vl_map:
            stem_lower = file.stem.lower()
            ext_lower = file.suffix.lower()
            for key, candidate in vl_map.items():
                # 去掉扩展名后比较，且扩展名要一致
                key_stem = key[: -len(ext_lower)] if key.endswith(ext_lower) else key
                if key_stem == stem_lower:
                    vl_item = candidate
                    logger.debug(
                        "vision_first: vision_vl 模糊匹配 '%s' → '%s'",
                        file.name, key,
                    )
                    break
        if vl_item is not None:
            if vl_item.confidence >= move_conf_threshold:
                # vision_vl 匹配成功且置信度达标 → 直接移动
                vl_cat = _get_category_for_item(file, vl_item.file_type)
                if vl_cat is None:
                    logger.info("vision_first: 跳过 Folder 类型文件 '%s'", file.name)
                    files_handled += 1
                    continue
                vl_parent, vl_sub = vl_cat
                vl_dest_dir = target / "Agent-Organized" / vl_parent / vl_sub
                vl_dest_dir.mkdir(parents=True, exist_ok=True)
                try:
                    vl_dest_name = file.name
                    vl_dest_path = vl_dest_dir / vl_dest_name
                    if vl_dest_path.exists():
                        stem, suffix = file.stem, file.suffix
                        n = 1
                        while (vl_dest_dir / f"{stem}_{n}{suffix}").exists():
                            n += 1
                        vl_dest_name = f"{stem}_{n}{suffix}"
                    shutil.move(str(file), str(vl_dest_dir / vl_dest_name))
                    if detection_cache is not None:
                        detection_cache.clear()
                    vision_processed += 1
                    files_handled += 1
                    percent = int(files_handled / total * 100)
                    progress_callback(
                        f"移动 {file.name} → {vl_parent}/{vl_sub}/ [vision_vl] conf={vl_item.confidence:.2f}",
                        percent,
                    )
                    logger.info(
                        "vision_first: vision_vl 移动 '%s' → %s/%s/ (conf=%.2f)",
                        file.name, vl_parent, vl_sub, vl_item.confidence,
                    )
                except Exception as exc:
                    logger.warning("vision_first: vision_vl 移动失败 '%s': %s，加入失败列表", file.name, exc)
                    files_handled += 1
                    failed_files.append(file)
                continue  # 跳过后续 pywinauto 逻辑
            else:
                # vision_vl 匹配成功但置信度低于阈值 → 加入低置信度列表
                logger.warning(
                    "vision_first: vision_vl 文件 '%s' 置信度 %.2f 低于阈值 %.2f，加入低置信度列表",
                    file.name, vl_item.confidence, move_conf_threshold,
                )
                low_conf_files.append((file, vl_item.confidence))
                files_handled += 1
                continue  # 跳过后续 pywinauto 逻辑
        # vl_item 为 None：不 continue，让现有 pywinauto 逻辑完整执行

        ext = file.suffix.lower()
        cat = FILE_CATEGORY_MAP.get(ext, ("Others", "Other"))
        category_parent, category_sub = cat
        dest_dir_path = target / "Agent-Organized" / category_parent / category_sub
        dest_dir_path.mkdir(parents=True, exist_ok=True)

        # 尝试在 Explorer 窗口中定位文件坐标（可选，失败不影响移动）
        file_cx: int | None = None
        file_cy: int | None = None
        file_confidence: float = 1.0  # 未经视觉定位时默认置信度为 1.0（OS 直接移动）
        if explorer_win is not None:
            try:
                from automation.vision_box_drawer import BoundingBoxDict  # noqa: PLC0415
                file_item = explorer_win.child_window(title=file.name, control_type="ListItem")
                rect = file_item.rectangle()
                file_cx = (rect.left + rect.right) // 2
                file_cy = (rect.top + rect.bottom) // 2

                # pywinauto 精确定位到 UI 元素，置信度设为 1.0
                file_confidence = 1.0
                logger.info(
                    "vision_first: 定位文件 '%s' 坐标 (%d, %d) confidence=%.2f",
                    file.name, file_cx, file_cy, file_confidence,
                )

                # 写入 DetectionCache：label 用真实文件名，供 apply_task_boost 匹配
                if detection_cache is not None:
                    detection_cache.update([BoundingBoxDict(
                        bbox=[
                            int(rect.left),
                            int(rect.top),
                            int(rect.right),
                            int(rect.bottom),
                        ],
                        label=file.name,   # 真实文件名，供任务上下文匹配
                        confidence=file_confidence,
                    )])
            except Exception as exc:
                # 无法通过 pywinauto 定位，降级为 OS 移动，置信度标记为低
                file_confidence = 0.4
                logger.debug(
                    "vision_first: 无法定位文件 '%s' 坐标 (confidence=%.2f): %s",
                    file.name, file_confidence, exc,
                )
                # 写入低置信度框到缓存，预览中显示红色框
                if detection_cache is not None:
                    detection_cache.update([BoundingBoxDict(
                        bbox=[0, 0, 1, 1],  # 坐标未知，用占位符
                        label=f"{file.name} (未定位)",
                        confidence=file_confidence,
                    )])

        # --- 置信度门控 ---
        # 门控开启（threshold > 0）且置信度低于阈值时，收集到待确认列表，不立即移动
        if move_conf_threshold > 0.0 and file_confidence < move_conf_threshold:
            logger.warning(
                "vision_first: 文件 '%s' 置信度 %.2f 低于门控阈值 %.2f，加入待确认列表",
                file.name, file_confidence, move_conf_threshold,
            )
            low_conf_files.append((file, file_confidence))
            if detection_cache is not None:
                detection_cache.clear()
            files_handled += 1
            continue  # 跳过本文件，不移动

        # 移动文件（置信度达标，或门控关闭）
        try:
            dest_name = file.name
            dest_path = dest_dir_path / dest_name
            if dest_path.exists():
                stem, suffix = file.stem, file.suffix
                n = 1
                while (dest_dir_path / f"{stem}_{n}{suffix}").exists():
                    n += 1
                dest_name = f"{stem}_{n}{suffix}"

            # 如果定位到坐标，写入 DetectionCache 供预览显示（不做实际点击）
            if file_cx is not None and file_cy is not None:
                pass  # 坐标仅用于 DetectionCache，shutil.move 不需要点击

            shutil.move(str(file), str(dest_dir_path / dest_name))

            # 移动成功后清空缓存
            if detection_cache is not None:
                detection_cache.clear()

            vision_processed += 1
            files_handled += 1
            percent = int(files_handled / total * 100)
            mode_tag = "vision+os" if file_cx is not None else "os"
            progress_callback(
                f"移动 {file.name} → {category_parent}/{category_sub}/ [{mode_tag}] conf={file_confidence:.2f}",
                percent,
            )
            logger.info(
                "vision_first: 成功移动 '%s' → %s/%s/ (confidence=%.2f)",
                file.name, category_parent, category_sub, file_confidence,
            )
        except Exception as exc:
            logger.warning("vision_first: 移动失败 '%s': %s，加入失败列表", file.name, exc)
            if detection_cache is not None:
                detection_cache.clear()
            files_handled += 1
            failed_files.append(file)

    # --- 处理低置信度文件（门控拦截的文件）---
    if low_conf_files:
        progress_callback(
            f"发现 {len(low_conf_files)} 个低置信度文件，等待用户确认…", 0
        )
        lines = "\n".join(f"  **{p.name}** (置信度 {c:.2f})" for p, c in low_conf_files[:10])
        if len(low_conf_files) > 10:
            lines += f"\n  ...等 {len(low_conf_files) - 10} 个文件"
        confirm_msg = (
            f"以下文件视觉识别置信度较低（红色框），是否仍然移动？\n{lines}\n\n"
            "选择「否」将跳过这些文件，保持原位。"
        )
        if confirm_callback is not None:
            should_move = confirm_callback(confirm_msg)
        else:
            should_move = _show_low_confidence_dialog(low_conf_files)
        if should_move:
            logger.info("vision_first: 用户确认移动 %d 个低置信度文件", len(low_conf_files))
            for i, (file, conf) in enumerate(low_conf_files):
                if stop_event.is_set():
                    return
                ext = file.suffix.lower()
                lc_cat = FILE_CATEGORY_MAP.get(ext, ("Others", "Other"))
                lc_parent, lc_sub = lc_cat
                dest_dir_path = target / "Agent-Organized" / lc_parent / lc_sub
                dest_dir_path.mkdir(parents=True, exist_ok=True)
                try:
                    dest_name = file.name
                    dest_path = dest_dir_path / dest_name
                    if dest_path.exists():
                        stem, suffix = file.stem, file.suffix
                        n = 1
                        while (dest_dir_path / f"{stem}_{n}{suffix}").exists():
                            n += 1
                        dest_name = f"{stem}_{n}{suffix}"
                    shutil.move(str(file), str(dest_dir_path / dest_name))
                    logger.info("低置信度文件已移动（用户确认）: %s → %s/%s/", dest_name, lc_parent, lc_sub)
                except Exception as move_exc:
                    logger.warning("低置信度文件移动失败，跳过: %s，原因: %s", file.name, move_exc)
                done = files_handled + i + 1
                percent = int(done / total * 100)
                progress_callback(
                    f"移动 {file.name} → {lc_parent}/{lc_sub}/ [low_conf={conf:.2f}]", percent
                )
        else:
            for file, conf in low_conf_files:
                logger.warning(
                    "vision_first: 用户拒绝移动低置信度文件，跳过: %s (conf=%.2f)",
                    file.name, conf,
                )
                progress_callback(f"跳过低置信度文件: {file.name} (conf={conf:.2f})", 0)

    # 处理失败文件
    if failed_files:
        names = [f.name for f in failed_files[:10]]
        file_list = "\n".join(f"  **{n}**" for n in names)
        if len(failed_files) > 10:
            file_list += f"\n  ...等 {len(failed_files) - 10} 个文件"
        confirm_msg = f"以下文件视觉识别失败，是否使用 OS 方式移动？\n{file_list}"
        if confirm_callback is not None:
            use_os_fallback = confirm_callback(confirm_msg)
        else:
            use_os_fallback = _show_fallback_dialog(failed_files)
        if use_os_fallback:
            for i, file in enumerate(failed_files):
                if stop_event.is_set():
                    return
                ext = file.suffix.lower()
                fb_cat = FILE_CATEGORY_MAP.get(ext, ("Others", "Other"))
                fb_parent, fb_sub = fb_cat
                dest_dir_path = target / "Agent-Organized" / fb_parent / fb_sub
                dest_dir_path.mkdir(parents=True, exist_ok=True)
                try:
                    dest_name = file.name
                    dest_path = dest_dir_path / dest_name
                    if dest_path.exists():
                        stem, suffix = file.stem, file.suffix
                        n = 1
                        while (dest_dir_path / f"{stem}_{n}{suffix}").exists():
                            n += 1
                        dest_name = f"{stem}_{n}{suffix}"
                    shutil.move(str(file), str(dest_dir_path / dest_name))
                    logger.info("OS 兜底移动: %s → %s/%s/", dest_name, fb_parent, fb_sub)
                except Exception as move_exc:
                    logger.warning("OS 兜底移动失败，跳过: %s，原因: %s", file.name, move_exc)
                done = files_handled + len(low_conf_files) + i + 1
                percent = int(done / total * 100)
                progress_callback(f"移动 {file.name} → {fb_parent}/{fb_sub}/ [os_fallback]", percent)
        else:
            for file in failed_files:
                logger.warning("用户拒绝 OS 兜底，跳过: %s", file.name)

    progress_callback("任务完成", 100)
