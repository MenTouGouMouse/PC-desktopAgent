"""
快速诊断 Qwen-VL 调用链是否正常工作。
运行方式：python debug_qwen_vl.py
"""
import logging
import os
import sys

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Step 1: 检查 API Key
from dotenv import load_dotenv
load_dotenv("config/.env")

api_key = os.environ.get("DASHSCOPE_API_KEY", "")
print(f"\n[1] DASHSCOPE_API_KEY: {'已设置 (' + api_key[:8] + '...)' if api_key else '❌ 未设置'}")
if not api_key:
    print("    → 这是根本原因，Qwen-VL 无法调用")
    sys.exit(1)

# Step 2: 截图
print("\n[2] 截图测试...")
try:
    from perception.screen_capturer import ScreenCapturer
    capturer = ScreenCapturer()
    screenshot = capturer.capture_full()
    h, w = screenshot.shape[:2]
    print(f"    ✓ 截图成功: {w}x{h}")
    import cv2
    cv2.imwrite("debug_screenshot.png", screenshot)
    print(f"    → 截图已保存到 debug_screenshot.png")
except Exception as e:
    print(f"    ❌ 截图失败: {e}")
    sys.exit(1)

# Step 3: 调用 Qwen-VL
print("\n[3] 调用 Qwen-VL API...")
try:
    from automation.qwen_vl_recognizer import QwenVLRecognizer, QwenVLAPIError
    recognizer = QwenVLRecognizer()
    items = recognizer.recognize_file_icons(screenshot)
    print(f"    ✓ 识别成功，共 {len(items)} 个文件项:")
    for item in items:
        print(f"      - name={item.name!r}  type={item.file_type}  conf={item.confidence:.2f}  bbox={item.bbox}")
except QwenVLAPIError as e:
    print(f"    ❌ QwenVLAPIError: {e}")
    sys.exit(1)
except Exception as e:
    print(f"    ❌ 未知错误: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# Step 4: 检查名称匹配
print("\n[4] 名称匹配测试（模拟桌面文件）...")
test_files = ["个人简历.pdf", "个人简历(1).pdf", "个人简历(兼职).pdf"]
vl_map = {item.name.lower(): item for item in items if item.name}
print(f"    vl_map 中的 key: {list(vl_map.keys())[:10]}")
for fname in test_files:
    match = vl_map.get(fname.lower())
    status = f"✓ 匹配 conf={match.confidence:.2f}" if match else "✗ 未匹配"
    print(f"    {fname!r}: {status}")

print("\n诊断完成。")
