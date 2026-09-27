# Deepdoc / OCR 运行时依赖部署说明

当前项目的文件解析主链路已经接入 OCR：

1. `DoclingDocumentParser` 先做 native parse。
2. 根据页面质量选择 `native` / `region_ocr` / `full_ocr`。
3. 当策略为 `region_ocr` 或 `full_ocr` 时，调用配置化 OCR runtime。
4. `OCR_ENGINE=auto` 时优先使用 Deepdoc；Deepdoc 不可用时使用 RapidOCR fallback。

## 1. 推荐部署策略

本项目支持三种 OCR runtime 配置：

```dotenv
OCR_ENGINE="auto"
```

- `auto`：优先 Deepdoc，失败后使用 RapidOCR。
- `deepdoc`：只使用 Deepdoc，不可用时报错。
- `rapidocr`：只使用 RapidOCR。

当前 DeepDoc 采用子进程适配器：

- 主 FastAPI 后端继续使用项目主虚拟环境 `.venv`。
- DeepDoc 单独安装在后端目录下的 `.venv_deepdoc`。
- 主进程通过 `DEEPDOC_PYTHON` 调用 `.venv_deepdoc/bin/python` 执行 `deepdoc-lib`。
- DeepDoc 模型文件放在项目内 `backend/models/deepdoc`。

本地开发可直接使用：

```dotenv
OCR_ENGINE="deepdoc"
OCR_PDF_RENDER_SCALE=2.0
OCR_MAX_PAGES=20
DEEPDOC_PYTHON="./.venv_deepdoc/bin/python"
DEEPDOC_MODEL_HOME="./models/deepdoc"
DEEPDOC_TIMEOUT_SECONDS=180
```

如果 DeepDoc 暂不可用，也可以把 `OCR_ENGINE` 切回 `rapidocr`。

## 2. 安装主后端依赖

进入后端目录并激活虚拟环境：

```bash
cd /Users/wangboqing/AI_Development/Agent/Agent_Project/studying_abroad_life_assistant/study_abroad_assistant/backend
source ../.venv/bin/activate
```

安装更新后的依赖：

```bash
pip install -r requirements.txt
```

关键 OCR 依赖包括：

- `rapidocr`
- `onnxruntime`
- `pypdfium2`
- `pillow`

## 3. 安装 DeepDoc 独立运行时

不要把 `deepdoc-lib` 安装到主 `.venv`。`deepdoc-lib 0.2.2` 对 `huggingface-hub` 和 `setuptools` 的版本要求与主后端已有依赖存在冲突，因此使用独立虚拟环境：

```bash
cd /Users/wangboqing/AI_Development/Agent/Agent_Project/studying_abroad_life_assistant/study_abroad_assistant/backend

python3.13 -m venv .venv_deepdoc
source .venv_deepdoc/bin/activate

python -m pip install -U pip
python -m pip install "setuptools>=75.2.0,<76.0.0"
python -m pip install deepdoc-lib
```

macOS 需要 OpenMP 运行库，否则 `xgboost` 可能无法加载：

```bash
brew install libomp
```

## 4. 下载模型到项目内

```bash
cd /Users/wangboqing/AI_Development/Agent/Agent_Project/studying_abroad_life_assistant/study_abroad_assistant/backend
source .venv_deepdoc/bin/activate

mkdir -p models/deepdoc
export DEEPDOC_MODEL_HOME="$(pwd)/models/deepdoc"
deepdoc-download-models
```

模型会落在：

```text
/Users/wangboqing/AI_Development/Agent/Agent_Project/studying_abroad_life_assistant/study_abroad_assistant/backend/models/deepdoc
```

## 5. 配置环境变量

编辑 `backend/.env`：

```dotenv
OCR_ENGINE="deepdoc"
OCR_PDF_RENDER_SCALE=2.0
OCR_MAX_PAGES=20
DEEPDOC_PYTHON="./.venv_deepdoc/bin/python"
DEEPDOC_MODEL_HOME="./models/deepdoc"
DEEPDOC_TIMEOUT_SECONDS=180
```

如果希望 DeepDoc 不可用时自动尝试 RapidOCR：

```dotenv
OCR_ENGINE="auto"
```

## 6. 独立运行时自测

```bash
cd /Users/wangboqing/AI_Development/Agent/Agent_Project/studying_abroad_life_assistant/study_abroad_assistant/backend
source .venv_deepdoc/bin/activate
export DEEPDOC_MODEL_HOME="$(pwd)/models/deepdoc"

python - <<'PY'
from deepdoc import PdfParser, DocxParser, ExcelParser, HtmlParser

PdfParser()
print("DeepDoc runtime ok")
PY
```

## 7. 验收运行时状态

启动后端：

```bash
cd /Users/wangboqing/AI_Development/Agent/Agent_Project/studying_abroad_life_assistant/study_abroad_assistant/backend
source ../.venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

检查 OCR runtime：

```bash
curl http://127.0.0.1:8000/api/files/ocr/deepdoc/status
```

期望看到：

```json
{
  "available": true,
  "package": "ocr",
  "configured_engine": "deepdoc",
  "deepdoc_available": true,
  "active_engine": "deepdoc"
}
```

如果 `available=false`，优先检查：

- `.env` 中 `DEEPDOC_PYTHON` 是否指向 `backend/.venv_deepdoc/bin/python`。
- `.venv_deepdoc` 中是否安装 `deepdoc-lib`。
- macOS 是否已安装 `libomp`。
- `DEEPDOC_MODEL_HOME` 是否指向 `backend/models/deepdoc`。
- 是否已执行 `deepdoc-download-models`。

## 8. 主链路验收

准备一份扫描版 PDF，上传后触发文件解析或作业分析。

OCR 成功时，解析结果 metadata 中应出现：

```json
{
  "ocr": {
    "status": "applied",
    "engine": "deepdoc",
    "pages": 1
  }
}
```

`engine` 会反映实际 runtime，例如 `deepdoc` 或 `rapidocr`；具体可用状态可通过 status endpoint 查看。

## 9. 注意事项

- OCR 会增加解析耗时，`OCR_MAX_PAGES` 用于限制单文件 OCR 页数。
- `OCR_PDF_RENDER_SCALE` 越高，识别效果可能越好，但速度和内存消耗也会增加。
- DeepDoc 子进程超时时间由 `DEEPDOC_TIMEOUT_SECONDS` 控制。
- `deepdoc-lib` 依赖与主后端依赖隔离，不要把它加入主 `requirements.txt`。
- 本阶段不做云端 OCR 服务调用，避免引入额外账号、费用和隐私边界。
