1. OCR\屏幕识别放到左边
2. 导航栏删除无用信息
3. 展示文件整理的过程流程
4. 完善文件整理功能

5. 准备视频流程录制用于答辩（放在PPT内）
6. 寻找其他的视觉识别替代方案（类千问视觉API）
7. 不要存在有问题的地方，解决掉小问题。
8. 完成论文，大概4月底第一版，做了什么，怎么做的，实现的技术细节，达成的效果这个思路完成论文。背景意义按照模板填写。

---

# 智能安装 software_installer.py 快照

## 快照版本1（原始轮询模式）

主动轮询查找按钮，有超时报错，进度条提前推进。
`run_software_installer` 核心循环逻辑：

```python
total = len(INSTALL_STEPS)
current_percent = 0

try:
    for i, step in enumerate(INSTALL_STEPS):
        if stop_event.is_set():
            return

        step_percent = int(i / total * 100)
        progress_callback(f"正在查找：{step.step_name}", step_percent)

        deadline = time.monotonic() + step.timeout
        found = False
        candidates = [step.button_text] + (step.aliases or [])

        while time.monotonic() < deadline:
            if stop_event.is_set():
                return
            for candidate in candidates:
                try:
                    win_rect = _activate_installer_window(pkg.stem)
                    # ... 视觉/静默识别 ...
                    result = element_locator.locate_by_text_visual_with_fallback(
                        screenshot, candidate, window_title_hint=pkg.stem,
                    )
                    cx = x + w // 2 + coord_offset[0]
                    cy = y + h // 2 + coord_offset[1]
                    if not action_engine.click(cx, cy):
                        raise RuntimeError(f"点击失败")
                    found = True
                    break
                except Exception as exc:
                    logger.warning("候选文字 %r 定位失败：%s", candidate, exc)
            if found:
                break
            time.sleep(0.5)

        if not found:
            if step.optional:
                progress_callback(f"跳过（未找到）：{step.button_text}", step_percent)
                continue
            progress_callback(msg, step_percent)
            raise TimeoutError(...)

        current_percent = int((i + 1) / total * 100)
        progress_callback(step.step_name, current_percent)
except Exception:
    progress_callback("安装异常终止", current_percent)
    raise
```

INSTALL_STEPS（4个）：

- 下一步（optional）
- 我同意（optional）
- 安装（optional）
- 完成（required）

---

## 快照版本2（用户点击监听模式，当前版本）

不主动轮询，监听用户鼠标左键点击，点击后立刻推进步骤。
视觉识别已注释，仅靠用户点击驱动进度。

INSTALL_STEPS（5个）：

- 下一步（optional）
- 下一步(2)（optional）
- 我同意（optional）
- 安装（optional）
- 完成（required）

`run_software_installer` 核心循环逻辑：

```python
from pynput import mouse as _pynput_mouse

_last_click: list[tuple[int, int] | None] = [None]
_click_event: threading.Event = threading.Event()

def _on_click(x, y, button, pressed):
    if pressed and button == _pynput_mouse.Button.left:
        _last_click[0] = (int(x), int(y))
        _click_event.set()

_mouse_listener = _pynput_mouse.Listener(on_click=_on_click)
_mouse_listener.start()
progress_callback("正在识别按钮", 0)

step_index = 0
try:
    while step_index < total:
        if stop_event.is_set():
            return
        step = INSTALL_STEPS[step_index]
        _click_event.clear()
        while not _click_event.wait(timeout=0.1):
            if stop_event.is_set():
                return
        click_pos = _last_click[0]
        if click_pos is None:
            continue
        _click_event.clear()

        step_index += 1
        current_percent = int(step_index / total * 100)

        def _push(pct=current_percent):
            progress_callback("✓ 已成功点击按钮", pct)
            if step_index < total:
                progress_callback("正在识别按钮", pct)

        threading.Thread(target=_push, daemon=True).start()

    progress_callback("智能安装完成", 100)
finally:
    _mouse_listener.stop()
```

---

## 回滚说明

- 回滚到版本1：将 `run_software_installer` 里从 `logger.info("安装模式：%s（用户点击监听模式）"` 到结尾替换为版本1的轮询代码，并将 INSTALL_STEPS 改回4个步骤。
- 回滚到版本2：当前代码即为版本2。
