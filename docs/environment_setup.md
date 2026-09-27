# 留学生活助手环境配置说明

本文档用于配置 `study_abroad_assistant` 项目的本地开发环境。

## 1. 基础要求

- Python：建议使用 Python 3.11 或 3.12；项目要求 `>=3.11`。
- Node.js：建议 Node.js 20 LTS 或更高版本。
- PostgreSQL：需要启用 `pgvector` 扩展。
- Redis：用于后续任务队列、缓存和会话状态。

## 2. 后端环境

进入后端目录：

```bash
cd study_abroad_assistant/backend
```

创建并激活虚拟环境：

```bash
python3.11 -m venv ../.venv
source ../.venv/bin/activate
```

如果本机没有 `python3.11`，也可以使用：

```bash
python3 -m venv ../.venv
source ../.venv/bin/activate
```

如果文档解析依赖 `docling` 在 Python 3.13 下安装失败，优先切换到 Python 3.11 或 3.12 重新创建虚拟环境。

安装运行依赖：

```bash
pip install -r requirements.txt
```

如果需要运行测试，安装开发依赖：

```bash
pip install -r requirements-dev.txt
```

复制环境变量文件：

```bash
cp .env.example .env
```

然后编辑 `.env`，至少确认以下配置：

```dotenv
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/study_abroad_assistant"
REDIS_URL="redis://localhost:6379/0"
LLM_BASE_URL="https://api.openai.com/v1"
LLM_API_KEY="你的 API Key"
UPLOAD_STORAGE_DIR="./.data/uploads"
OCR_ENGINE="deepdoc"
DEEPDOC_PYTHON="./.venv_deepdoc/bin/python"
DEEPDOC_MODEL_HOME="./models/deepdoc"
DEEPDOC_TIMEOUT_SECONDS=180
```

如需启用 Browser MCP 网页浏览/抽取工具，需要二选一配置 HTTP JSON-RPC endpoint 或 stdio MCP server command：

```dotenv
BROWSER_MCP_ENABLED=true

# 方式 A：连接已有 Browser MCP HTTP JSON-RPC 服务
BROWSER_MCP_ENDPOINT="http://127.0.0.1:8765/mcp"
BROWSER_MCP_AUTH_TOKEN=""

# 方式 B：由后端按需拉起本地 stdio MCP server
BROWSER_MCP_COMMAND="npx -y your-browser-mcp-server"

# Browser MCP 服务中的工具名，可按实际 server 调整
BROWSER_MCP_TOOL="browser.search_extract"
BROWSER_MCP_SEARCH_TOOL=""
BROWSER_MCP_EXTRACT_TOOL=""
BROWSER_MCP_TIMEOUT_SECONDS=30
```

如需启用 Travel Agent 的 Google Maps 路线和地点 provider：

```dotenv
GOOGLE_MAPS_API_KEY="你的 Google Maps API Key"
GOOGLE_MAPS_LANGUAGE="zh-CN"
GOOGLE_MAPS_REGION="GB"
GOOGLE_MAPS_TIMEOUT_SECONDS=10
```

Email Agent 默认支持 `dry_run` provider，不会真实发送外部邮件。若要启用 QQ 或 Outlook SMTP 真实发送，需要配置对应 provider，并且调用发送接口时传入 `approved=true`：

```dotenv
QQ_SMTP_HOST="smtp.qq.com"
QQ_SMTP_PORT=465
QQ_SMTP_USERNAME="你的 QQ 邮箱"
QQ_SMTP_PASSWORD="QQ 邮箱 SMTP 授权码"
QQ_SMTP_FROM_EMAIL="你的 QQ 邮箱"
QQ_SMTP_FROM_NAME="Study Abroad Assistant"

OUTLOOK_SMTP_HOST="smtp.office365.com"
OUTLOOK_SMTP_PORT=587
OUTLOOK_SMTP_USERNAME="你的 Outlook 邮箱"
OUTLOOK_SMTP_PASSWORD="Outlook SMTP 密码或应用密码"
OUTLOOK_SMTP_FROM_EMAIL="你的 Outlook 邮箱"
OUTLOOK_SMTP_FROM_NAME="Study Abroad Assistant"
```

当前 Outlook provider 使用 SMTP + STARTTLS；如果后续改为 Microsoft Graph/OAuth，需要单独配置 OAuth app 和 token 管理。

配置完成后可通过以下接口检查 provider 状态：

```bash
curl http://127.0.0.1:8000/api/tools/status
curl http://127.0.0.1:8000/api/email/providers/status
```

启动后端：

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

## 3. 数据库准备

创建数据库后，需要启用扩展并执行初始化 SQL。

```bash
createdb study_abroad_assistant
psql study_abroad_assistant -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql study_abroad_assistant -f app/db/migrations/001_initial_schema.sql
```

如果本机 PostgreSQL 用户或密码不是 `postgres/postgres`，请同步修改 `.env` 中的 `DATABASE_URL`。

## 4. Redis

本地启动 Redis 后确认可连接：

```bash
redis-cli ping
```

期望返回：

```text
PONG
```

## 5. 前端环境

进入前端目录：

```bash
cd study_abroad_assistant/frontend
```

安装依赖：

```bash
npm install
```

启动前端：

```bash
npm run dev
```

默认访问地址：

```text
http://127.0.0.1:5173/
```

前端 Vite 代理会把 `/api` 请求转发到：

```text
http://127.0.0.1:8000
```

因此完整联调时需要同时启动后端。

## 6. 测试与检查

后端测试：

```bash
cd study_abroad_assistant/backend
source ../.venv/bin/activate
pytest
```

后端语法检查：

```bash
python -m compileall app tests
```

前端构建：

```bash
cd study_abroad_assistant/frontend
npm run build
```

## 7. 当前版本注意事项

- OCR 已进入文件解析主链路；Deepdoc / RapidOCR 运行时部署见 [deepdoc_runtime_deployment.md](deepdoc_runtime_deployment.md)。
- 邮件 Agent 默认生成草稿并支持 dry-run；配置 QQ/Outlook SMTP 且用户批准后可真实发送。
- Travel Agent 不执行订票或支付。
- Finance Agent 只提供预算整理，不提供金融、税务或法律建议。
- Wellbeing Agent 只做低风险支持和危机识别，不做诊断。
