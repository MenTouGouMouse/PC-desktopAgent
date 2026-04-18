# CV 桌面自动化智能体

基于计算机视觉与大语言模型融合的 PC 桌面自动化智能体。接收自然语言指令（如"打开微信，向文件传输助手发送'你好'"），自动完成界面理解、GUI 元素定位、鼠标键盘模拟，实现端到端桌面任务自动化。

## 核心能力

- 自然语言指令解析（Qwen3.5-Plus / DashScope API）
- 多级 GUI 元素定位，带优先级降级：本地 YOLOv8 GUI 检测（`models/gui_detector.pt`，离线最快，模型文件不存在时自动跳过）→ pywinauto Win32 控件 API → 阿里云 GUI-Plus → Qwen3-VL（OpenAI 兼容接口）→ Tesseract OCR → OpenCV 模板匹配 → 经验坐标偏移
- 鼠标/键盘模拟（自动检测进程 DPI awareness：通过 `GetProcessDpiAwareness` 读取 awareness 级别，Per-Monitor Aware（≥2）时 `pyautogui.moveTo` 直接使用物理坐标；UNAWARE/SYSTEM_AWARE 时将物理坐标除以 scale 转换为逻辑坐标后传入；awareness 和 scale 在模块级缓存，避免每次点击重复读取；屏幕尺寸边界检查基于 `mss` 物理像素；鼠标移动使用三次贝塞尔曲线生成拟人化轨迹，带随机控制点、ease-out 速度曲线和微抖动；点击前先 `moveTo` 到目标位置并等待 100ms，点击后等待 200ms；支持中文输入）
- 任务流程录制（pynput）与回放（JSON 模板）
- Gradio Web UI，实时屏幕预览
- 双数据库记忆系统：ChromaDB（向量检索）+ SQLite（结构化存储）
- 进程隔离：UI 进程与执行进程通过 `multiprocessing.Queue` 通信

---

## 环境要求

### 操作系统

- Windows 10 / 11（推荐）
- 支持多显示器及 DPI 缩放（100% / 125% / 150%）

### Python

- Python **3.10+**（严格要求，使用了 `match` 语句和新式类型注解）

### Tesseract OCR

需要在系统中安装 Tesseract，并配置中文语言包：

1. 下载安装：[Tesseract at UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)
2. 安装时勾选 **Chinese Simplified** 语言包（`chi_sim`）
3. 记录安装路径（如 `C:\Program Files\Tesseract-OCR\tesseract.exe`）
4. 在 `config/settings.yaml` 中配置路径（见[配置说明](#配置说明)）

---

## 安装步骤

### 1. 克隆仓库

```bash
git clone <repository-url>
cd cv-desktop-automation-agent
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

或使用一键安装脚本：

```bash
bash install.sh
```

### 4. 配置环境变量

```bash
copy config\.env.example config\.env
```

然后编辑 `config/.env`，填入实际的 API Key（见[配置说明](#配置说明)）。

---

## 配置说明

### 环境变量（`config/.env`）

参考 `config/.env.example`，填写以下必需变量：

| 变量名                     | 说明                                                                                          | 是否必填                   |
| -------------------------- | --------------------------------------------------------------------------------------------- | -------------------------- |
| `DASHSCOPE_API_KEY`        | 通义千问 / Qwen-VL API Key，从 [DashScope 控制台](https://dashscope.console.aliyun.com/) 获取 | **必填**                   |
| `ALIYUN_ACCESS_KEY_ID`     | 阿里云视觉智能平台 Access Key ID                                                              | 使用阿里云 GUI-Plus 时必填 |
| `ALIYUN_ACCESS_KEY_SECRET` | 阿里云视觉智能平台 Access Key Secret                                                          | 使用阿里云 GUI-Plus 时必填 |

> 注意：`config/.env` 已加入 `.gitignore`，请勿将实际密钥提交到版本库。

### 运行参数（`config/settings.yaml`）

非敏感运行参数，缺失时使用默认值并记录警告日志：

| 参数                        | 默认值      | 说明                                 |
| --------------------------- | ----------- | ------------------------------------ |
| `capture.fps`               | `15`        | 屏幕捕获帧率（≥15 fps）              |
| `capture.default_monitor`   | `0`         | 默认目标显示器索引                   |
| `retry.max_attempts`        | `3`         | 最大重试次数                         |
| `retry.initial_wait_sec`    | `1`         | 初始重试等待时间（秒）               |
| `retry.jitter_max_sec`      | `1`         | 重试抖动最大值（秒）                 |
| `retry.element_timeout_sec` | `10`        | 元素等待超时时间（秒）               |
| `agent.model`               | `qwen-plus` | LLM 模型 ID                          |
| `agent.max_iterations`      | `20`        | Agent 最大迭代次数                   |
| `agent.memory_max_tokens`   | `2000`      | 记忆系统最大 token 数                |
| `ui.preview_fps`            | `15`        | UI 实时预览帧率                      |
| `ui.queue_timeout_sec`      | `30`        | 执行进程响应超时时间（秒）           |
| `ocr.tesseract_cmd`         | ——          | Tesseract 可执行文件路径（必须配置） |

**Tesseract 路径配置示例：**

```yaml
ocr:
  tesseract_cmd: "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
```

---

## 启动命令

确保已激活虚拟环境并完成配置后：

```bash
python main.py
```

启动后，Gradio Web UI 将在本地运行，默认地址为 `http://127.0.0.1:7860`。

界面功能：

- 自然语言指令输入框 + 执行按钮
- 录制开始/停止按钮（录制结果保存至 `recordings/`）
- 实时屏幕预览（≥15 fps，识别到元素时用红色矩形框标注；叠加实时鼠标光标（绿色十字准星 + 圆点，与截图同步绘制，消除传输延迟带来的滞后感）；可通过"🔍 显示识别框"按钮启用视觉检测框叠加，检测由独立后台线程以 ≤2 次/秒频率运行，不影响预览帧率）
- 操作日志实时展示区

---

## 测试命令

```bash
# 全量测试 + HTML 覆盖率报告
pytest --cov=perception --cov=decision --cov=execution --cov=task --cov=ui --cov-report=html tests/

# 仅单元测试（快速）
pytest tests/unit/ -v

# 排除端到端测试
pytest -m "not e2e" --cov=perception --cov=decision --cov=execution --cov=task tests/
```

覆盖率报告生成在 `htmlcov/index.html`。

### 覆盖率要求

| 模块          | 最低覆盖率 |
| ------------- | ---------- |
| `perception/` | 80%        |
| `decision/`   | 75%        |
| `execution/`  | 85%        |
| `task/`       | 80%        |
| 整体          | 75%        |

激活虚拟环境

cd到根目录，启动项目
cd ..
python main_gui.py

框架更新
cd frontend
npm run build
