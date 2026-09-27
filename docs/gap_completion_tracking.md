# Gap Completion Tracking

本文档用于跟踪 `gap_analysis_against_initial_plan.md` 中列出的补全进度，防止遗漏。

## 阶段 1 缺陷收敛

状态：进行中。

来源：

- 外部输入：《阶段1缺陷分析总结.md》
- 项目内追踪文档：[phase1_defect_convergence_tracking.md](phase1_defect_convergence_tracking.md)
- Agent 审计基线：[agent_capability_migration_audit.md](agent_capability_migration_audit.md)

待收敛重点：

- 已完成：LangGraph 成为 `/api/chat` 主编排链路，不再只保留 graph shell。
- 已完成：补齐调度者 Agent -> Worker Agent 的正式 interface。
- 已完成：逐 Agent 迁移完整性审计和正式完成定义。
- 已完成：Travel Agent 正式能力边界重设，输出 source / confidence / tool_status，禁止伪装真实路线或地点信息。
- 已完成：Browser MCP / Travel Maps provider abstraction 和 availability status。
- 已完成：Travel Agent 从边界重设升级为 Google Maps live provider-informed 计划。
- 已完成：Travel Maps live provider execution，覆盖 Google Directions / Places。
- 已完成：Browser MCP live provider execution，支持 HTTP JSON-RPC endpoint 与 stdio MCP server command。
- 已完成：QQ 邮箱与 Outlook 邮件 provider、审批发送和发送审计。
- 已完成：补齐阶段耗时观测，覆盖 router、memory、tool、worker、LLM、RAG、OCR/document parsing，并通过 `trace_spans` 入库与 `/api/chat` latency summary 返回。
- 已完成：调度者 Agent 与 Worker Agent 架构完善，多意图执行计划可驱动多个 Worker 按依赖分层执行；同层无依赖 Worker 支持并行，WorkerContext 注入 execution step、前序 artifacts、tool availability 和显式 tool execution result。

开发约束：

- 已有方案明确的模块不得再用 demo、规则占位、模板输出或最小版本替代。
- 外部依赖不可用时必须显式标记 unavailable，并保留正式接口边界。

## P0

### Phase 7：Router + Orchestrator + Chat API

状态：已补齐。

已完成：

- 统一 `/api/chat` 入口。
- 结构化 `ChatRequest` / `ChatResponse`。
- `IntentRouter` 规则路由，输出 `RouterOutput`。
- `AgentState`。
- `StudyAbroadOrchestrator`。
- 可选 `AgentRunRecorder`，可写入 `agent_runs`。
- 已串联 Worker：
  - Wellbeing
  - Travel
  - Finance
  - Assignment
  - Task Planner
  - Email
- 信息不足时返回 `missing_information`，不虚构结果。
- 最小 LangGraph shell：`backend/app/agents/orchestrator/graph.py`。
- Phase 7 单元测试。

增强补齐已完成：

- 将 Memory loading 写入 graph node。
- 将 tool execution 写入 graph node。
- 将 worker dispatch 从服务方法迁移为显式 graph node。
- 将前端 ChatComposer 接入 `/api/chat`。
- 已更新 `backend/tests/test_orchestrator_graph.py` 覆盖 route → memory → tools → dispatch trace。
- 已更新前端 `ChatComposer` 展示 `/api/chat` 响应、missing information 与 `memory_context`。

### Phase 8：Memory + 多轮对话

状态：已补齐。

已完成：

- Redis short-term memory。
- PostgreSQL long-term memory。
- Memory Router。
- namespace access policy。
- topic continuity detection。
- reference resolution。
- query rewrite。
- conversation / conversation_messages 数据模型。
- `/api/chat` 已接入 MemoryManager。
- 支持 short-term recent messages。
- 支持 long-term memory repository 和 namespace 检索。
- 支持稳定偏好的长期记忆候选写入。
- 指代 query rewrite 后会重新路由。
- 最小 LangGraph shell 已加入 memory node。
- Phase 8 单元测试。

增强补齐已完成：

- 使用真实 token counter 替代字符估算。
- 接入 LLM memory compression。
- 接入 LLM topic ambiguity judgement。
- 长期记忆增加 embedding hybrid retrieval。
- 更细的敏感等级和 retention policy。
- 前端展示 memory_context。
- 已新增 `backend/app/memory/token_counter.py`、`compression.py`、`llm_judge.py`、`policy.py`。
- 已更新 `LongTermMemoryRepository.search` 支持 embedding hybrid retrieval。
- 已更新 `MemoryManager` 支持压缩摘要、LLM topic judgement、embedding 查询与保留策略。
- 已更新 `backend/tests/test_memory_manager.py` 覆盖 token counter 与敏感保留策略。

### Phase 9：Notice → Action + Global Planner

状态：已补齐。

已完成：

- `ActionItem` schema。
- Notice / email / bill / tenancy parser。
- Global planner input abstraction。
- Cross-agent planning horizon。
- Reminder worker。
- `/api/notice/parse`。
- `/api/planner/global`。
- `/api/planner/reminders/due`。
- `/api/chat` 已接入 Notice → Action → Global Planner 初步闭环。
- 支持解析：
  - assignment deadline
  - bill due
  - tenancy action
  - travel event
  - appointment
  - email follow-up
  - generic review task
- Phase 9 单元测试。

增强补齐已完成：

- Notice parser 接入 LLM 结构化抽取和 verifier。
- 支持多 action item 的更细粒度 evidence span。
- Reminder worker 增加 email channel 实际发送队列。
- Global Planner 读取已有 tasks/events，而不是只接收 request.existing_blocks。
- Global Planner 与 Memory Manager 联动，读取用户偏好和时间习惯。
- 增加前端 Notice Action review UI。
- 已新增 `backend/app/agents/notice/llm_extractor.py` 与 `verifier.py`。
- 已更新 `EvidenceRef` 支持 `start_char` / `end_char`。
- 已新增 `/api/planner/reminders/email-queue` draft-only email queue。
- 已更新 `/api/planner/global` 可从 DB repository 读取已有 tasks/events，且 request 支持 `memory_preferences`。
- 已新增前端 `NoticeActionReviewPanel`。
- 已更新 `backend/tests/test_notice_action.py` 与 `backend/tests/test_global_planner.py` 覆盖 evidence span、email queue、memory preferences 和 existing blocks。

## P1

### Phase 10：Assignment Research Workflow

状态：已补齐。

已完成：

- Deepdoc OCR 适配入口：`backend/app/documents/ocr.py`。
- Parser 已输出 OCR strategy metadata，支持 native / region OCR / full OCR 策略标记。
- ArXiv search：`backend/app/agents/research/arxiv.py`。
- Web search：`backend/app/agents/research/web_search.py`。
- Paper retrieval：`backend/app/agents/research/paper.py`。
- Research query generator：`backend/app/agents/research/query_generator.py`。
- Assignment research workflow：`backend/app/agents/research/workflow.py`。
- Research source RAG indexing API：`/api/assignment/research/index-source`。
- Assignment idea verifier：`backend/app/agents/assignment/idea_verifier.py`。
- Assignment research API：
  - `/api/assignment/research/queries`
  - `/api/assignment/research/arxiv`
  - `/api/assignment/research/web`
  - `/api/assignment/research/papers/download`
  - `/api/assignment/research/workflow`
  - `/api/assignment/research/index-source`
  - `/api/assignment/ideas/verify`
- Phase 10 单元测试。

增强补齐已完成：

- 接入真实 Deepdoc SDK 配置和运行时依赖校验。
- Web search 更换为稳定 provider 或增加 provider registry。
- Paper retrieval 增加 metadata enrichment、PDF 摘要化和重复检测。
- Research source RAG indexing 增加端到端数据库集成测试。
- Assignment idea verifier 接入 LLM verifier，提高语义判断能力。
- 前端增加 research workflow / idea verification review UI。
- RAG retrieval 增加 reranker、阈值策略和 research-specific filters。
- 已新增 Deepdoc runtime status：`/api/files/ocr/deepdoc/status`。
- 已新增 `backend/app/agents/research/web_providers.py` provider registry。
- 已更新 Paper retrieval 输出 sha256、duplicate detection、title、summary、metadata。
- 已更新 `IndexDocumentRequest.source_type`，`/api/assignment/research/index-source` 写入 `research_source`。
- 已新增可选 PostgreSQL/pgvector 集成测试：设置 `TEST_DATABASE_URL` 后执行真实 Research source RAG indexing DB 流程；普通测试环境保留服务链路测试。
- 已更新 Assignment idea verifier 支持 LLM JSON verifier 与规则回退。
- 已新增前端 `ResearchReviewPanel`。
- 已更新 RAG retrieval 支持 `min_score`、`content_types`、`research_only`、rerank。
- 已更新 `backend/tests/test_assignment_research.py`、`test_hybrid_retriever.py`、`test_health.py` 覆盖上述增强。

### Phase 11：Travel / Finance 深化 + Tools

状态：已补齐。

已完成：

- Tool registry：`backend/app/tools/registry.py`。
- Permission-aware tool executor：`backend/app/tools/executor.py`。
- Tool API：
  - `/api/tools`
  - `/api/tools/run`
- Weather tool：`weather.lookup`，实现于 `backend/app/tools/weather.py`。
- Travel itinerary generator：`backend/app/agents/travel/itinerary.py`。
- Travel itinerary API：`/api/travel/itinerary`。
- Finance bill parser：`backend/app/agents/finance/bill_parser.py`。
- Finance bill parser API：`/api/finance/bills/parse`。
- Budget goals：`backend/app/agents/finance/budget_goals.py`。
- Budget goals API：`/api/finance/goals/review`。
- Phase 11 单元测试。

增强补齐已完成：

- Tool execution logging 入库。
- Tool registry 增加 ArXiv / Web search / reminder / calendar adapters 的统一包装。
- Weather tool 增加 provider fallback 和失败时的可恢复错误分类。
- Travel itinerary 增加 Google Maps Directions / Places provider，并保持订票和支付审批边界。
- Travel itinerary 从模板块升级为 provider-informed blocks：路线时长、地点候选、天气输入和预算依据进入多日计划。
- Travel 与 Task Planner 的 action/event handoff 自动化，并已接入确认后真实落库。
- Travel memory confirmation flow：pending candidate 不进入长期检索，确认后转换为正式 travel user preference。
- Finance bill parser 接入文件解析结果和 LLM verifier，提高复杂账单抽取能力。
- Budget goals 接入 finance memory namespace 和 recurring expense 周期。
- 已新增 `backend/app/tools/logging.py`，`ToolExecutor` 与 `/api/tools/run` 可写入 tool run 日志。
- 已新增 `backend/app/tools/adapters.py`，统一包装 ArXiv / Web search / reminder / calendar draft adapters。
- 已更新 Weather tool 返回 fallback 与 `recoverable_error`。
- 已新增 Travel `LocalRouteProvider`、Google Maps provider、route/place suggestions、planner handoff items，并保持 booking/payment approval boundary。
- 已新增 Travel persistence service，覆盖 Planner 真实落库和 Memory candidate confirmation。
- 已更新 Finance bill parser 支持文件解析输入与 LLM verifier。
- 已更新 Budget goals 支持 `recurring_contribution` 与 `memory_preferences`。
- 已更新 `backend/tests/test_phase11_tools_travel_finance.py` 覆盖 registry、Google Maps provider parsing、provider-informed itinerary、route handoff、recurring contribution。

## P2

### Phase 12：Fitness + Social Content Agent

状态：已补齐。

已完成：

- Fitness Agent：`backend/app/agents/fitness/service.py`。
- Fitness schema：`backend/app/schemas/fitness.py`。
- Fitness API：`/api/fitness/plan`。
- Fitness 已接入 `/api/chat` orchestrator。
- Social Content Agent：
  - `backend/app/agents/social_content/platform.py`
  - `backend/app/agents/social_content/copy_generator.py`
  - `backend/app/agents/social_content/safety.py`
  - `backend/app/agents/social_content/service.py`
- Social Content schema：`backend/app/schemas/social_content.py`。
- Social Content API：`/api/social-content/drafts`。
- Social Content 已接入 `/api/chat` orchestrator。
- `fitness-planning` Skill。
- `social-content-writing` Skill。
- 前端 Fitness Plan 面板。
- 前端 Social Content 面板。
- Phase 12 单元测试。

增强补齐已完成：

- Fitness 与 Task Planner 的 schedule integration 自动化。
- Fitness 接入 memory namespace，记录稳定偏好时需要用户确认。
- Fitness 增加更细的目标周期和渐进负荷策略。
- Social Content 增加更完整的平台规范和多版本候选稿。
- Social Content 接入 LLM 写作生成和更强的 privacy verifier。
- 如需图片生成，单独设计 image generation tool，不并入当前文案 Agent。
- 已更新 Fitness 输出 `schedule_tasks`，可交给 Task Planner 放入日程。
- 已新增 Fitness `memory_candidates`，namespace 固定为 `fitness`，默认需要用户确认。
- 已新增 Fitness `progression`，按周输出渐进负荷与复盘策略。
- 已新增 Social platform standards、多版本候选稿、platform fit notes。
- 已新增 `LlmSocialCopyGenerator`，API 路径可选 LLM 写作生成，失败自动回退规则模板。
- 已增强 Social privacy verifier，支持输入校验、生成稿复核与合并风险等级。
- 已新增独立 `image_generation_tool` 设计输出，状态为 `designed_not_enabled`，不并入文案 Agent 执行。
- 已更新前端 Fitness / Social 面板展示 schedule、progression、memory candidate、platform standard、image generation boundary。
- 已更新 `backend/tests/test_phase12_fitness_social.py` 覆盖 schedule integration、memory confirmation、多稿与平台规范。

## 验证记录

- `./.venv/bin/python -m compileall backend/app backend/tests`：通过。
- `./.venv/bin/pytest backend/tests`：68 passed, 1 skipped。跳过项为可选 PostgreSQL/pgvector 集成测试，需设置 `TEST_DATABASE_URL` 后运行。
- `npm run build`：通过。
