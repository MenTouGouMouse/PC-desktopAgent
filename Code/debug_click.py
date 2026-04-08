"""
鼠标点击诊断脚本 — 直接运行此文件，观察输出。
用法：python debug_click.py
"""
import ctypes
import sys
import time

import pyautogui

print("=" * 60)
print("【1】pyautogui 基本信息")
print(f"  FAILSAFE       = {pyautogui.FAILSAFE}")
print(f"  PAUSE          = {pyautogui.PAUSE}")
print(f"  screen size    = {pyautogui.size()}")
print(f"  current pos    = {pyautogui.position()}")

print("\n【2】DPI awareness")
try:
    v = ctypes.c_int(0)
    ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(v))
    awareness_map = {0: "UNAWARE", 1: "SYSTEM_AWARE", 2: "PER_MONITOR_AWARE"}
    print(f"  DPI awareness  = {v.value} ({awareness_map.get(v.value, '?')})")
except Exception as e:
    print(f"  DPI awareness  = 读取失败: {e}")

print("\n【3】DPIAdapter 读取的 scale_factor")
try:
    from perception.dpi_adapter import DPIAdapter
    d = DPIAdapter()
    print(f"  scale_factor   = {d.scale_factor}")
    print(f"  monitors       = {d._monitors}")
except Exception as e:
    print(f"  DPIAdapter 失败: {e}")

print("\n【4】测试 pyautogui.moveTo — 3 秒后移动到 (200, 200)")
print("  请观察鼠标是否移动...")
time.sleep(3)
try:
    before = pyautogui.position()
    pyautogui.moveTo(200, 200)
    after = pyautogui.position()
    print(f"  移动前: {before}")
    print(f"  移动后: {after}")
    if abs(after.x - 200) < 5 and abs(after.y - 200) < 5:
        print("  ✅ moveTo 正常工作")
    else:
        print(f"  ❌ moveTo 异常：期望 (200,200)，实际 {after}")
except Exception as e:
    print(f"  ❌ moveTo 抛出异常: {e}")

print("\n【5】测试 ctypes SetCursorPos — 移动到 (400, 300)")
try:
    ctypes.windll.user32.SetCursorPos(400, 300)
    time.sleep(0.2)
    pos = pyautogui.position()
    print(f"  SetCursorPos 后位置: {pos}")
    if abs(pos.x - 400) < 5 and abs(pos.y - 300) < 5:
        print("  ✅ SetCursorPos 正常工作")
    else:
        print(f"  ❌ SetCursorPos 异常：期望 (400,300)，实际 {pos}")
except Exception as e:
    print(f"  ❌ SetCursorPos 失败: {e}")

print("\n【6】测试 ActionEngine.click — 点击 (400, 300)")
try:
    from execution.action_engine import ActionEngine
    engine = ActionEngine()
    result = engine.click(400, 300)
    print(f"  ActionEngine.click 返回: {result}")
except Exception as e:
    print(f"  ❌ ActionEngine.click 抛出异常: {e}")
    import traceback
    traceback.print_exc()

print("\n【7】with_retry 装饰器检查")
try:
    from execution.retry_handler import with_retry
    print(f"  with_retry 导入成功: {with_retry}")
except Exception as e:
    print(f"  ❌ with_retry 导入失败: {e}")

print("\n" + "=" * 60)
print("诊断完成。请将以上输出粘贴给 Kiro。")
