# 阶段性收敛 1 记录

本文档记录针对《阶段性收敛1.md》的第一轮收敛结果。该外部文档作为需求输入，不作为运行时指令。

## 本轮已收敛

### 1. Notice Parser：LLM-first，规则 fallback

已完成：

- `NoticeActionParser.parse_async()` 改为优先调用 `LlmNoticeExtractor`。
- LLM 输出有效 `ActionItem` 时，直接进入 `NoticeActionVerifier` 校验。
- LLM 不可用、异常或无有效结构化结果时，再 fallback 到确定性规则解析。
- `/api/notice/parse` 和 `/api/chat` 中的 notice worker 均使用 notice 阶段模型。
- 单元测试覆盖：
  - LLM-first 路径。
  - LLM 空结果 fallback 规则路径。
  - evidence span 保持可用。

### 2. Intent Router：结构化多意图 + 槽位 + 依赖 + 不确定性

已完成：

- `RouterOutput` 增加：
  - `structured_intents`
  - `clarification_questions`
  - `fusion_metadata`
- `StructuredIntent` 支持：
  - `name`
  - `agent_intent`
  - `slots`
  - `condition`
  - `depends_on`
  - `missing_slots`
  - `confidence`
  - `source`
- Router 架构改为：
  - 语义向量相似度分类器：对用户输入和 intent prototype 做 embedding，并用 cosine similarity 排序。
  - 可选 LLM classifier。
  - voting fusion layer：语义向量结果与 LLM 结构化结果共同投票，分歧时保留可追溯元数据。
- 已支持 fallback intents：
  - `unknown`
  - `clarification_required`
  - `chitchat`
  - `out_of_scope`
  - `unsafe_request`
  - `system_command`
- 已支持典型多意图拆分：
  - `calendar.query_availability`
  - `calendar.create_event`
  - create event 依赖 query availability。
- `StudyAbroadOrchestrator` 已改用 `router.route_async()`，主链路会记录融合元数据。
- 同步 `route()` 仅作为无模型/测试 fallback，主链路不依赖单一路由规则。
- 单元测试覆盖：
  - 邮件 + 任务规划多意图。
  - 作业文件解析路由。
  - 日历查询 + 创建会议结构化拆分。
  - async Router 同时调用 semantic vector embedding 和 LLM，并以 vote 结果输出最终意图。
  - 不清晰输入 fallback 到澄清。

### 3. Deepdoc 自动进入文件解析主链路

已完成：

- `DoclingDocumentParser` 在完成 native parse 后，会根据 `parse_strategy` 判断是否需要 OCR。
- 当策略为 `region_ocr` 或 `full_ocr` 时，自动调用 `OcrDocumentProcessor(DeepdocOcrEngine())`。
- Deepdoc 不可用时，不再静默忽略，而是在 `metadata.ocr` 中记录：
  - `status: unavailable`
  - `engine: deepdoc`
  - `error`
- Deepdoc 可用时，OCR 文本会作为 `ParsedDocumentElement` 注入后续流程。
- 单元测试覆盖 parser 自动调用 Deepdoc 并追加 OCR 文本。

### 4. 分阶段模型配置

已完成：

- `Settings` 增加阶段模型配置：
  - `ROUTER_LLM_MODEL`
  - `ROUTER_EMBEDDING_MODEL`
  - `NOTICE_LLM_MODEL`
  - `ASSIGNMENT_LLM_MODEL`
  - `EMAIL_LLM_MODEL`
  - `SOCIAL_LLM_MODEL`
  - `MEMORY_LLM_MODEL`
- 新增 `get_stage_llm_client(stage)`。
- 已接入阶段：
  - router
  - notice
  - assignment
  - email
  - social
- `.env.example` 已补充对应配置项。
- 单元测试覆盖 router 阶段模型覆盖主模型。

### 5. 多意图执行规划器

已完成：

- 新增 `MultiIntentExecutionPlanner`。
- 新增 `MultiIntentExecutionPlan` / `ExecutionStep` schema。
- 支持根据 Router 的 `structured_intents` 生成执行步骤。
- 支持依赖关系：
  - `calendar.create_event` 可依赖 `calendar.query_availability`。
- Calendar provider 边界已按本轮决策收敛：
  - 不接 Google/Outlook Calendar。
  - 不写真实日历。
  - 会议类动作转换成本地 `PlannerOutput.tasks` 和 `email` channel reminder draft。
- `/api/chat` 遇到 calendar-style 多意图时会返回 `multi_intent_execution` artifact。
- 新增 `/api/execution/plan`，可单独生成多意图执行计划。
- 单元测试覆盖：
  - calendar workflow 转任务和邮件提醒草稿。
  - orchestrator 返回 `multi_intent_execution` artifact。

### 6. 前端真实工作流联动

已完成：

- 前端 `ChatApiResponse` 类型补齐 `router`、`artifacts`、`trace`。
- `sendChatMessage()` 默认开启 `persist_agent_runs`，使 Router 观测和 agent run 可入库。
- 主工作台优先展示真实 chat artifacts：
  - `assignment_analysis`
  - `notice_parse`
  - `planner_output`
  - `fitness_plan`
  - `social_content`
  - `email_draft`
  - `multi_intent_execution`
- 新增 `ExecutionPlanPanel` 展示多意图步骤、依赖和 email reminder drafts。
- 新增 Workflow 操作按钮调用 `/api/execution/plan`。
- 保留 sample 数据作为无真实响应时的 fallback。

### 7. Router 观测数据入库

已完成：

- 新增 `router_observations` 数据模型和 migration。
- 新增 `RouterObservationRepository`。
- `/api/chat` 注入 `RouterObservationRepository`，每次 Router 完成后记录：
  - user / conversation / trace
  - 原始 message
  - primary intent / confidence
  - structured intents
  - fusion metadata
  - clarification questions
- 观测写入失败只记录 trace，不阻断用户对话。
- 单元测试覆盖 repository 写入 metadata。

## 验证结果

- `./.venv/bin/python -m compileall backend/app backend/tests`：通过。
- `./.venv/bin/pytest backend/tests`：78 passed, 1 skipped。
- `npm run build`：通过。

跳过项仍为可选 PostgreSQL/pgvector 集成测试，需设置 `TEST_DATABASE_URL` 后运行。

## 下一步

1. 部署 Deepdoc 运行时依赖。
2. 部署前确认数据库已应用 `router_observations` migration。
3. 后续如需要更完整的 workflow UI，可继续把 Assignment / Notice / Research 做成表单化流程；本轮已完成真实 artifact 联动。
