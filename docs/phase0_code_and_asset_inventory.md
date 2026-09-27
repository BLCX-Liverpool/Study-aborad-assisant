# Phase 0 代码与资产盘点

状态：已完成

权威设计来源：`docs/study_abroad_assistant_technical_design.md`

本文档用于固化留学生活助手项目 Phase 0 的盘点结论。内容严格限定在已经确认的实施版技术设计范围内，不引入新的产品功能。

## 1. Phase 0 目标

Phase 0 包含四个交付物：

- 原项目可迁移模块清单。
- 依赖与运行风险清单。
- MVP 范围冻结。
- 新项目目录结构确认。

Phase 0 不复制运行时代码，不安装依赖，不运行任何 demo。

## 2. 新项目目录

新助手的正式产品代码放在：

```text
study_abroad_assistant/
  backend/
  frontend/
  docs/
  tests/
```

原始 `awesome-llm-apps` 目录只作为参考素材：

```text
starter_ai_agents/
advanced_ai_agents/
mcp_ai_agents/
rag_tutorials/
generative_ui_agents/
voice_ai_agents/
```

规则：后续只在审查后复制经过筛选的 schema、prompt、架构模式或小型工具逻辑。不要把完整 demo app 或其框架运行时整体复制进新项目。

## 3. MVP 范围冻结

第一版实施范围仅限于：

- Assignment Agent。
- Task Planner。
- Email Agent。
- 文件解析与 RAG。
- Memory service。
- Tool permission layer。
- Trace、Evidence 与 Observability。
- FastAPI 后端。
- React/TypeScript 前端。
- PostgreSQL、Redis 与 pgvector。

MVP 明确不包含：

- Travel Agent 实现。
- Finance Agent 实现。
- Wellbeing Agent 实现。
- Fitness Agent 实现。
- Social Content Agent 实现。
- Podcast/audio briefing 实现。
- 真实邮件发送。
- 真实日历写入。
- 浏览器自动化。
- MCP server 执行。
- 支付、删除或外部账户操作。

以上非 MVP 模块只能在后续阶段经过明确确认后再实现。

## 4. 已确认的技术约束

主运行时技术栈固定为：

```text
FastAPI + LangGraph + Pydantic + PostgreSQL + Redis + React/TypeScript
```

新项目不能把原 demo 中的多个框架混入主运行时：

- 不把 Agno 作为中心 Agent 框架。
- 不把 Google ADK 作为中心 Agent 框架。
- 不把 AG2/AutoGen 作为中心 Agent 框架。
- 不使用 Streamlit 作为产品 UI。
- MVP 实施阶段不启动 MCP server。

原项目只作为设计参考，不作为可直接接入的模块。

## 5. 迁移清单

### 5.1 Travel Planner Agent Team

来源：

```text
advanced_ai_agents/multi_agent_apps/agent_teams/ai_travel_planner_agent_team/
```

可参考资产：

- FastAPI app 生命周期与 router 结构：
  - `backend/api/app.py`
  - `backend/router/plan.py`
- 后台任务状态追踪模式：
  - `backend/models/plan_task.py`
  - `backend/migrations/create_plan_tasks_table.sql`
- 数据库 repository 模式：
  - `backend/repository/plan_task_repository.py`
  - `backend/services/db_service.py`
- 前端技术栈参考：
  - `client/package.json`
  - `client/app/`
  - `client/components/`
- Travel request schema 可作为后续 Travel Agent 的参考：
  - `backend/models/travel_plan.py`

迁移决策：

- 只复用架构思路。
- 不复制 Agno team 编排。
- 不把 Firecrawl、Exa、fast-flights 工具复制进 MVP。
- 不采用当前 Markdown -> LLM -> JSON 的结构化转换方式作为生产方案。

原因：

- 已确认架构要求使用 LangGraph，并让 Agent 直接输出 Pydantic 结构化结果。
- Travel 不属于 MVP。

### 5.2 Financial Coach Agent

来源：

```text
advanced_ai_agents/multi_agent_apps/ai_financial_coach_agent/
```

可参考资产：

- Pydantic 结构化输出 schema 风格。
- 顺序式领域拆分思路：
  - budget analysis
  - savings strategy
  - debt reduction
- CSV expense 解析思路。

迁移决策：

- 只参考 schema 模式。
- 不复制 Google ADK 运行时。
- MVP 不实现 Finance Agent。

后续适配方向：

- 若后续实现，应改造成留学生预算模型：房租、押金、学费、生活费、兼职收入、汇率、旅行支出、紧急备用金。

### 5.3 Mental Wellbeing Agent 与 Breakup Recovery Agent

来源：

```text
advanced_ai_agents/multi_agent_apps/ai_mental_wellbeing_agent/
starter_ai_agents/ai_breakup_recovery_agent/
```

可参考资产：

- 子任务拆分：
  - assessment
  - action plan
  - follow-up
- 支持性表达风格。
- 输入维度，例如压力、睡眠、支持系统、近期变化。

迁移决策：

- 只参考 prompt 拆分方式。
- 不复制 AutoGen、Agno、DuckDuckGo 或 Streamlit 运行时。
- MVP 不实现 Wellbeing Agent。

后续约束：

- 必须包含危机识别。
- 不能进行诊断。
- 对高风险状态必须引导寻求专业帮助。
- 敏感记忆必须使用严格访问策略。

### 5.4 Blog to Podcast Agent

来源：

```text
starter_ai_agents/ai_blog_to_podcast_agent/
```

可参考资产：

- 文档或网页转 audio briefing 的产品思路。

迁移决策：

- 不属于 MVP。
- 不复制 ElevenLabs 或 Firecrawl 集成。
- MVP 不实现音频生成。

### 5.5 Journalist Agent

来源：

```text
advanced_ai_agents/single_agent_apps/ai_journalist_agent/
```

可参考资产：

- search -> write -> edit 工作流思路。

迁移决策：

- 不属于 MVP。
- 不复制 SerpAPI、Newspaper4k、Agno 或 Streamlit 运行时。

后续适配方向：

- 若后续批准，可改造成 Social Content Agent。

### 5.6 Health and Fitness Agent

来源：

```text
advanced_ai_agents/single_agent_apps/ai_health_fitness_agent/
```

可参考资产：

- 用户 profile 表单字段和基础饮食/健身 prompt 思路。

迁移决策：

- 不属于 MVP。
- 不复制 Gemini、Agno、Streamlit 运行时。

### 5.7 MCP Travel Planner

来源：

```text
mcp_ai_agents/ai_travel_planner_mcp_agent_team/
```

可参考资产：

- 后续 MCP 集成概念。
- 实时住宿和地图数据场景。

迁移决策：

- 延后。
- 不运行。
- 不复制进 MVP。

原因：

- 它会通过 `npx` 启动 MCP server。
- 它使用 Airbnb 和 Google Maps MCP 工具。
- 它需要外部 API key 和网络执行。

### 5.8 RAG Tutorials

来源：

```text
rag_tutorials/hybrid_search_rag/
rag_tutorials/agentic_typed_rag_pydanticai/
```

可参考资产：

- `hybrid_search_rag` 中的混合检索思路。
- `agentic_typed_rag_pydanticai` 中的引用与拒答门控思路。
- 精确 source metadata 和 quote validation 思路。

迁移决策：

- 只参考思路。
- 不使用 Streamlit UI。
- 不采用 RAGLite 或 Pydantic AI 作为中心 RAG 运行时。
- 按已确认方案实现 Docling + 结构化 chunking + BM25 + pgvector。

## 6. 依赖与运行风险清单

| 领域 | 原项目中观察到的情况 | 风险 | MVP 决策 |
| --- | --- | --- | --- |
| 多 Agent 框架 | Agno、Google ADK、AG2/AutoGen | 抽象和依赖冲突 | 只使用 LangGraph |
| Demo UI 框架 | 多个 Agent 使用 Streamlit | 不适合作为产品前端 | 只使用 React/TypeScript |
| MCP 执行 | MCP Travel 中使用 `npx` 启动 MCP server | 会启动外部服务，并依赖网络/API key | 延后 |
| 浏览器自动化 | Browser/MCP 示例 | 外部状态、权限和副作用不可控 | 延后 |
| Web scraping | Firecrawl、Newspaper4k、SerpAPI | 网络、成本、API key、合规风险 | MVP 中除已批准的 Web/ArXiv search 接口外不接入 |
| 搜索工具 | SerpAPI、DuckDuckGo、Google Search | 外部依赖和结果质量不稳定 | 后续封装在 permissioned tool interface 后再接入 |
| 敏感领域 | Wellbeing 和 breakup support | 安全和隐私风险 | 不进入 MVP |
| 财务建议 | Financial Coach demos | 准确性和责任风险 | 不进入 MVP |
| 文本转音频 | ElevenLabs | 额外 API key 和成本 | 不进入 MVP |
| LLM 转 JSON | Travel Planner structured output converter | 输出漂移和校验不稳定 | 优先使用原生 Pydantic 结构化输出 |
| 全仓库安装 | 100+ demo，各自依赖不同 | 依赖冲突和安全风险 | 永不全仓库安装 |

## 7. Phase 1 的 MVP 实施输入

Phase 1 应从干净的后端骨架开始，位置为：

```text
study_abroad_assistant/backend/
```

Phase 1 必须建立的基础：

- FastAPI application。
- 配置层。
- OpenAI-compatible LLM provider 抽象。
- SQLAlchemy model base。
- PostgreSQL connection configuration。
- Redis configuration placeholder。
- Pydantic schema package。
- Agent run、tool run、task、event、reminder、file、document chunk、memory 模型定义。
- 测试骨架。

Phase 1 不能实现：

- 真实 Assignment Agent 推理。
- 真实 RAG indexing。
- 真实 Email Agent drafting。
- 外部 MCP tools。
- Travel、Finance、Wellbeing、Fitness、Social 或 Podcast 模块。

## 8. 后续阶段的文件解析与 RAG 输入

已批准的文件解析路径为：

```text
Upload
  -> Docling parser
  -> PDF page quality analyzer
  -> native / region OCR / full OCR strategy decision
  -> unified document model
  -> structural chunking
  -> BM25 index
  -> pgvector index
  -> evidence builder
```

Phase 1 应准备相关 schema 和数据库字段，但真实 parser 实现属于 Phase 2，除非明确前移。

后续必须预留的字段已经体现在技术设计中：

- `section_path`
- `heading_level`
- `content_type`
- `bbox_json`
- `parse_strategy`
- `text_quality_score`
- `image_area_ratio`
- `source_metadata_json`

## 9. Phase 0 决策

- 新产品代码放在 `study_abroad_assistant/`。
- 根目录下原 `awesome-llm-apps` 素材保持参考用途，除非后续阶段明确迁移选定代码。
- MVP 范围冻结为 Assignment、Task Planner、Email、文件解析/RAG、Memory、Permissions、Trace 和 Evidence。
- 不整体复制任何原始 demo app。
- Phase 0 不运行任何高风险工具。
- Phase 1 可以开始后端基础设施建设。

