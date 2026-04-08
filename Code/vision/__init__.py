"""
vision — 视觉叠加层模块。

包含 OverlayDrawer：后台截图线程，负责 mss 截图 → OpenCV 检测框绘制
→ JPEG 压缩 → base64 编码，供 PyWebView 前端实时预览。
"""
