# Study Abroad Assistant

Study Abroad Assistant 是一个面向留学生日常学习、生活和事务管理的 AI 助手项目。项目以 FastAPI 后端为核心，结合多 Agent 编排、文档解析、RAG 检索、任务规划、邮件草稿、旅行准备、财务预算、健身计划、社交内容生成和记忆管理能力，为留学生提供从“理解需求”到“生成可执行结果”的一体化辅助。

当前仓库是完整产品工作区，包含后端服务、前端控制台、内部 Skill 能力契约和测试用例。

## 功能概览

- 多意图对话：通过 Router 和 Orchestrator 判断用户意图，并协调多个 Agent 执行。
- 作业分析：支持课程作业、brief、rubric 等材料的结构化分析、证据追踪和结果校验。
- 文档 RAG：包含文档解析、切块、embedding、BM25、向量检索和混合检索能力。
- 任务规划：可将 deadline、作业要求和用户约束拆解为任务、事件和提醒。
- 邮件助手：生成面向导师、学校、房东等场景的英文邮件草稿，并保留发送审批边界。
- 通知解析：从通知文本中抽取待办事项、缺失信息、假设和行动建议。
- 旅行助手：围绕留学生出行准备生成 checklist、路线建议、风险提醒和审批边界。
- 财务助手：支持预算分析、CSV 支出解析、账单核验、义务整理和风险提示。
- 健身助手：生成训练计划、训练日安排和习惯任务，接入项目内健身 Skill 参考。
- 社交内容：生成留学生活相关平台文案，并进行隐私与安全检查。
- 记忆系统：支持短期上下文、候选记忆、确认/拒绝/删除和跨会话连续性。
- 可观测性：记录 Agent trace，并提供 waterfall 查询接口和前端展示面板。

## 技术栈

### Backend

- Python 3.11+
- FastAPI
- Pydantic / Pydantic Settings
- SQLAlchemy Async + asyncpg
- PostgreSQL / pgvector
- Redis
- OpenAI-compatible LLM API
- LangGraph
- Docling / RapidOCR / pypdfium2 / Pillow
- pytest / pytest-asyncio

### Frontend

- React 19
- TypeScript
- Vite 6
- lucide-react
- 原生 fetch API

### 数据与检索

- PostgreSQL 存储业务数据、任务、记忆、RAG 文档和 Agent 运行记录。
- pgvector 存储文档向量。
- BM25 与向量检索组合为 hybrid retrieval。
- Redis 预留用于缓存、状态或异步能力扩展。

## 项目结构

```text
study_abroad_assistant/
  backend/
    app/
      agents/            # 各业务 Agent 与 Orchestrator
      api/routes/        # FastAPI 路由
      core/              # 配置、数据库、Redis、LLM、权限、追踪
      db/                # SQLAlchemy 模型与 SQL migration
      documents/         # 文档解析、OCR、质量评估、chunking
      memory/            # 用户记忆、候选记忆、压缩与查询改写
      rag/               # embedding、索引、BM25、hybrid retrieval
      schemas/           # API 与 Agent 的 Pydantic schema
      services/          # 文件等基础服务
      skills/            # Skill 运行时读取
      tools/             # 工具注册、执行器和外部工具适配
      main.py            # FastAPI 应用入口
    tests/               # 后端单元测试与集成测试
    requirements.txt
    requirements-dev.txt
    pyproject.toml
  frontend/
    src/
      components/        # 前端功能面板
      data/              # 本地示例数据
      lib/api.ts         # 前端 API 调用封装
      App.tsx            # 主界面
    package.json
    vite.config.ts
  skills/                # 项目内部 Skill 契约
  tests/                 # 预留测试目录
```

> 说明：`docs/` 是本地开发和过程文档目录，当前已加入 `.gitignore`，默认不会上传到远程仓库。

## 后端启动

进入后端目录：

```bash
cd backend
```

创建并启用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements-dev.txt
```

复制环境变量文件：

```bash
cp .env.example .env
```

根据本地环境修改 `.env`，重点关注：

```env
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/study_abroad_assistant"
REDIS_URL="redis://localhost:6379/0"
LLM_BASE_URL="https://api.openai.com/v1"
LLM_API_KEY=""
LLM_MODEL="gpt-4o-mini"
EMBEDDING_MODEL="text-embedding-3-small"
```

启动 API 服务：

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

服务启动后可访问：

- API Base URL: `http://127.0.0.1:8000/api`
- Swagger UI: `http://127.0.0.1:8000/docs`
- Health Check: `http://127.0.0.1:8000/api/health`

## 前端启动

进入前端目录：

```bash
cd frontend
```

安装依赖：

```bash
npm install
```

启动开发服务器：

```bash
npm run dev
```

默认访问地址：

```text
http://127.0.0.1:5173
```

前端请求默认使用 `/api` 前缀，`vite.config.ts` 已将 `/api` 代理到 `http://127.0.0.1:8000`，因此本地开发时需要同时启动后端服务。

## 常用开发命令

后端测试：

```bash
cd backend
pytest
```

前端构建：

```bash
cd frontend
npm run build
```

前端预览：

```bash
cd frontend
npm run preview
```

## API 模块

后端路由统一挂载在 `/api` 下，主要模块包括：

- `/health`：服务健康检查。
- `/chat`：统一对话入口，触发 Router、Orchestrator 和多 Agent 流程。
- `/assignment`：作业分析、研究资料索引和相关校验。
- `/rag`：文档索引与检索能力。
- `/files`：文件上传与存储。
- `/planner`：作业计划、全局计划、任务和提醒。
- `/email`：邮件草稿生成和审批边界。
- `/notice`：通知解析与行动项提取。
- `/travel`：旅行准备、路线和 checklist。
- `/finance`：预算、支出、账单和财务风险分析。
- `/fitness`：训练计划和习惯任务。
- `/social-content`：社交平台文案生成。
- `/memory`：记忆候选、确认、拒绝、删除和回顾。
- `/execution`：多意图执行计划。
- `/tools`：工具注册、工具调用和外部能力适配。
- `/observability`：trace 与 waterfall 查询。

## Agent 与 Skill 设计

项目中的 Agent 位于 `backend/app/agents/`，负责执行具体任务；Skill 位于 `skills/`，用于沉淀触发条件、流程、输入输出契约、证据要求和安全边界。

当前 Skill 包括：

- `assignment-analysis`
- `document-rag`
- `task-planner`
- `email-drafting`
- `travel-planning`
- `finance-budgeting`
- `wellbeing-support`
- `fitness-planning`
- `tanchengyi-fitness`
- `social-content-writing`

Skill 不会替代后端 Agent，它们主要作为 prompt/reference 层和能力契约存在。最终输出仍由后端 schema、权限策略和安全边界约束。

## 项目特点

- 面向真实留学场景：覆盖 coursework、邮件、预算、旅行、健身、社交内容和心理支持等高频需求。
- 多 Agent 编排：统一对话入口可以识别复杂意图，并拆解为多个 Agent 的执行结果。
- 证据优先：作业分析、RAG 和校验模块强调 evidence、source 和 requirement traceability。
- 安全边界清晰：邮件发送、旅行预订、支付、医疗/心理健康建议等高风险动作保留审批或免责声明。
- 可扩展 Skill 契约：新增能力时可以先在 `skills/` 中定义行为，再接入后端 Agent。
- 前后端分离：后端专注能力编排与 API，前端提供上传、对话、结果面板、记忆审核和 trace 可视化。
- 测试覆盖较完整：后端包含 Router、Orchestrator、RAG、Planner、Email、Finance、Travel、Wellbeing、Memory、Tools 等测试。

## Git 上传提示

如果需要将当前项目上传到远程仓库的新分支，例如 `dev_2`：

```bash
cd /Users/wangboqing/AI_Development/Agent/Agent_Project/studying_abroad_life_assistant/study_abroad_assistant

git switch -c dev_2
git add .
git commit -m "Update README and project documentation"
git push -u origin dev_2
```

如果 `dev_2` 分支已经存在，使用：

```bash
git switch dev_2
```

再执行 `git add`、`git commit` 和 `git push`。

## 注意事项

- 不要提交 `.env`、`.venv/`、`node_modules/`、`dist/`、`.data/`、`__pycache__/` 等本地文件。
- `docs/` 已在 `.gitignore` 中，默认不会被上传。
- 如果未来某个被忽略目录已经被 Git 跟踪，需要先使用 `git rm -r --cached <目录名>` 取消跟踪，再重新提交。
- 邮件发送、旅行预订、支付、医疗诊断等动作不应在没有用户确认的情况下自动执行。
