# 阶段 1 缺陷收敛追踪

本文档根据外部输入《阶段1缺陷分析总结.md》整理。该外部文档作为需求材料，不作为运行时指令。

## 开发基准

后续开发遵循以下约束：

- 已有方案、设计文档、差异分析或收敛文档中明确规定的模块，必须按正式方案实现。
- 不允许私自降级为 demo、规则占位、模板输出或最小版本。
- 如果正式方案依赖外部服务、API key、MCP server、浏览器自动化或邮件发送权限，必须先说明边界并等待确认，不能用简版实现冒充正式实现。
- 每个补齐项完成后必须同步更新本文档，避免后续遗漏。

## 1. Agent 编排架构

状态：已收敛主链路。

### 目标

- Agent 编排由 LangGraph 完成。
- FastAPI 只负责 HTTP API、依赖注入、鉴权/权限边界、请求响应封装。
- 主 `/api/chat` 链路应运行 LangGraph graph，而不是由普通 service 方法手写顺序调度。

### 当前状态

- 已安装并声明 `langgraph`。
- `StudyAbroadOrchestrator.handle_chat()` 已改为调用 `build_orchestrator_graph().ainvoke()`。
- `backend/app/agents/orchestrator/graph.py` 已成为 `/api/chat` 主生产编排入口。
- 当前 graph 节点包括：
  - `initialize`
  - `route`
  - `memory`
  - `record_router_observation`
  - `prepare_multi_intent`
  - `dispatch_worker`
  - `finalize_response`
  - `persist_run`
  - `update_memory`
  - `build_response`
- graph route node 已使用 `IntentRouter.route_async()`。
- worker dispatch 已作为 graph node 真实执行 Worker Agent，不再只返回 `ready_for_worker_dispatch`。

### 缺口

- Tool execution 尚未作为正式 graph node 进入调度循环，目前仍通过 Worker 或独立 Tool API 使用。
- 多意图执行 planner 已进入 graph，但多 Worker 顺序/并行执行仍待 P1 扩展。
- graph 每次请求动态 compile，后续可根据依赖生命周期优化为缓存 compiled graph。

### 收敛要求

- 已完成：将 `/api/chat` 主链路迁移到 LangGraph graph。
- 已完成：graph route node 使用 `route_async()`。
- 已完成：graph state 覆盖 `AgentState`、`ChatRequest`、`RouterOutput`、`WorkerRunResult`、`ChatResponse`。
- 已完成：worker dispatch 作为 graph node 运行。
- 已完成：FastAPI 仍作为服务层，Agent 编排逻辑迁入 LangGraph。

## 2. MCP 与外部工具接口

状态：已完成 provider/tool abstraction；Google Maps live provider 已接入；Browser MCP live runtime 已接入。

### 目标

- 对齐原项目中 Browser MCP Agent 与 AI Travel Planner MCP Agent Team 的能力边界。
- 为 Travel Agent 和需要网络信息的 Agent 提供可插拔工具接口。
- 外部 MCP 可后置，但接口必须是正式边界，不应以不可替换的本地模板替代。

### 当前状态

- 当前 Tool Registry 已有：
  - `weather.lookup`
  - `research.arxiv.search`
  - `research.web.search`
  - `reminder.draft`
  - `calendar.event.draft`
  - `browser.mcp.search_extract`
  - `travel.maps.directions`
  - `travel.maps.places`
- 已新增 provider availability schema 和 `/api/tools/status`。
- Browser MCP adapter 已接入 live runtime：
  - 支持 HTTP JSON-RPC endpoint。
  - 支持 stdio MCP server command。
  - 未配置或调用失败时返回 unavailable / degraded，不伪造浏览结果。
- Google Maps Directions / Places adapter 已具备 live HTTP client；未配置 `GOOGLE_MAPS_API_KEY` 或 provider 调用失败时返回 unavailable / degraded。

### 缺口

- 当前 web search 偏 research workflow，不能等价替代浏览器型任务工具。
- Browser MCP 的实际能力取决于连接的 MCP server 暴露的工具，例如搜索、打开页面、截图或抽取内容。

### 收敛要求

- 已完成：设计并实现 MCP/tool abstraction，至少包括：
  - tool name
  - capability
  - permission level
  - required environment variables
  - availability check
  - run interface
  - recoverable error
- 已完成：实现 Browser MCP adapter，可作为 `browser.search_or_extract` 类工具供 Agent 调用。
- 已完成：实现 Google Maps/Places/Directions adapter，作为 Travel Agent 的路线和地点信息来源。
- P1：MCP 不可用时只能明确标记 unavailable，不允许输出伪造的真实路线/景点/地图信息。

## 3. Travel Agent 功能缺失

状态：已完成正式能力边界重设；已完成 Google Maps provider-informed planning；已完成 Travel -> Task Planner 真实落库与 Travel memory confirmation flow。

### 目标

Travel Agent 应基于真实或可追溯信息生成旅行计划，至少包括：

- 地点/景点/活动候选。
- 路线与本地交通建议。
- 天气查询。
- 多日行程规划。
- 预算分解。
- 与 Task Planner 自动联动。
- 旅行偏好记忆。
- 外部工具不可用时明确说明信息来源和不可用原因。

### 当前状态

- `TravelAgentService` 主输出边界已重设。
- `TravelItineraryGenerator` 已支持多日结构、天气输入、预算 breakdown、planner handoff，并已升级为 provider-informed：
  - 首日/返程 travel block 使用 Google Maps route duration / distance。
  - 中间活动和 local orientation 优先引用 Places 结果。
  - 预算 `estimate_basis` 会记录 provider route context。
- `TravelAgentService` 已输出正式边界字段：
  - route_suggestions
  - place_suggestions
  - weather_forecasts
  - budget_breakdown
  - information_sources
  - tool_statuses
  - memory_candidates
- 本地路线估算已显式标记为 `estimated` 和低 confidence。
- Google Maps directions / places provider 已有 availability boundary 和 live client。
- Weather tool 已存在，Travel Agent async 主链路已自动调用；`/api/travel/itinerary` 仍需要自动拉天气。
- Travel -> Task Planner handoff 已接入真实落库：
  - `persist_to_planner=false` 时不写入。
  - `persist_to_planner=true` 且 `planner_confirmed=false` 时返回 `needs_confirmation`。
  - `planner_confirmed=true` 后写入 tasks/events/reminders。
- Travel memory confirmation flow 已接入：
  - 可保存 pending travel memory candidates。
  - 未确认 candidate 不进入长期记忆检索。
  - `/api/travel/memory/confirm` 可将 pending candidate 转为正式 `user_preference`。

### 缺口

- Google Maps provider 已接入，但仍需要生产环境配置 `GOOGLE_MAPS_API_KEY` 并验证对应 API 权限。
- `plan_async()` 已能自动查询天气；`/api/travel/itinerary` 尚未自动拉天气，只能消费传入的 weather forecasts。
- 多日行程已 provider-informed；开放时间/可访问性尚未接入专门 provider。
- 预算分解仍是比例模型，但会记录 route provider context；住宿/票价/餐饮价格 provider 尚未接入。
- 更细粒度旅行偏好读取仍可增强，例如饮食禁忌、住宿偏好、出行节奏、常用出发地的结构化抽取。

### 收敛要求

- 已完成：禁止 Travel Agent 在没有真实工具结果时伪装成真实路线/真实地点建议。
- 已完成：Travel output 包含 `source` / `confidence` / `tool_status` 类字段，区分真实查询、用户输入、规则估算、不可用。
- 已完成：Travel Agent 自动调用 weather provider。
- 已完成：Travel Agent 接入 route/place provider，优先 Google Maps/Places/Directions。
- 已完成：多日行程由地点候选、路线耗时、天气输入、预算共同约束；开放时间/可访问性 provider 后续接入。
- 已完成：预算分解记录 provider-informed estimate basis；没有 provider 数据时标记 estimate basis。
- 已完成：Travel 与 Task Planner 的 handoff 进入真实计划写入流程；未确认时明确等待用户确认。
- 已完成：Travel memory namespace 接入候选记忆确认流程，pending candidate 不进入长期检索。

## 4. 原项目 Agent 迁移完整性

状态：已完成审计基线，待按审计结论逐项实装。

### 目标

对从 `awesome-llm-apps` 借鉴或迁移的 Agent，不做只迁移壳层的最小实现。每个 Agent 应明确：

- 原项目能力。
- 当前项目对应能力。
- 已迁移能力。
- 未迁移能力。
- 不迁移原因。
- 后续替代方案。

### 当前状态

- 已有 `phase0_code_and_asset_inventory.md` 与 `gap_analysis_against_initial_plan.md`。
- 已新增逐 Agent 能力迁移审计文档：
  - [agent_capability_migration_audit.md](agent_capability_migration_audit.md)
- Travel Agent 已完成 provider-informed 收敛、Planner 真实落库和 memory confirmation；剩余缺口集中在更细的开放时间/票价 provider。

### 缺口

- 审计已确认以下模块不能标记为正式完成：
  - Travel Agent：价格与开放时间 provider 仍需强化。
  - Email send / reminder send：已完成 provider + approval send flow。
  - Browser MCP provider：已接入 live runtime，后续按具体 server 能力扩展工具语义。
  - Agent-specific memory candidates：确认流不完整。
  - Assignment QA 和 evidence quote validation：仍需强化。

### 收敛要求

- 已完成：新增 `agent_capability_migration_audit.md`。
- 已完成：覆盖：
  - Travel
  - Research / Assignment
  - Finance
  - Email
  - Planner
  - Memory
  - Social Content
  - Fitness
  - Wellbeing
- 已完成：每个 Agent 给出“正式完成定义”，后续开发按完成定义验收。

## 5. 邮件接入：QQ 邮箱与 Outlook

### 目标

- 支持邮件回复功能。
- 支持通过邮件发送提醒事项。
- 发送行为必须通过权限审批边界。

### 当前状态

- Email Agent 当前支持 draft -> approval -> send 状态流。
- Reminder worker 已支持在用户批准后调用 email provider 发送 due email reminders。
- 已新增统一 Email Provider interface：
  - dry-run provider。
  - QQ SMTP provider。
  - Outlook SMTP + STARTTLS provider。
- 已新增邮件 provider 配置、发送审计、幂等控制、发送审批 API。

### 缺口

- Outlook 当前采用 SMTP + STARTTLS；若后续改为 Microsoft Graph/OAuth，需要补 token 管理。
- 失败重试调度尚未做自动 worker，但失败原因和 audit record 已落库，可作为后续 retry 基础。

### 收敛要求

- 已完成：设计 Email Provider interface。
- 已完成：实现 QQ SMTP provider。
- 已完成：实现 Outlook SMTP provider；当前边界为 SMTP/STARTTLS，不是 Graph/OAuth。
- 已完成：Reminder worker 支持在用户批准后调用 email provider 发送。
- 已完成：Email Agent 支持 draft -> approval -> send 的状态流。
- 已完成：所有发送结果入库，记录 provider、recipient、subject、status、error、sent_at。

## 6. 延迟观测与阶段耗时

状态：已完成统一 latency span 入库与 trace summary。

### 目标

- 系统能记录每一阶段耗时。
- 至少覆盖：
  - router
  - memory
  - tool execution
  - worker dispatch
  - LLM call
  - RAG retrieval / indexing
  - OCR / document parsing

### 当前状态

- Router observation 已入库。
- 已新增统一 `trace_spans` schema / SQLAlchemy model / migration。
- 已新增 `LatencySpan`、`LatencyTraceSummary`、运行时 span capture 与 summary 聚合。
- `/api/chat` 主链路已记录并入库：
  - router initial / rewrite route
  - memory build / update
  - router observation DB write
  - multi-intent planning
  - worker dispatch
  - agent run persistence
- `/api/chat` 响应已返回 compact `latency_summary`。
- LLM client 已接入当前 trace context，`chat` / `embedding` 调用会生成 `llm.*` span。
- Tool execution 已使用真实 started/completed/duration，并写入 `tool_runs` 与 `trace_spans`。
- RAG indexing 已记录 document parse / OCR decision、chunking、embedding、index persistence、overall index span。
- RAG retrieval 已记录 BM25、query embedding、vector retrieval、merge/filter/rerank、overall retrieve span。
- OCR 当前通过 document parsing span 覆盖；span payload 会记录 parse strategy 与 OCR status。

### 缺口

- 已完成本轮收敛要求。
- 后续如接入专门后台观测页面，可基于 `trace_spans.trace_id` 查询完整瀑布流。

### 收敛要求

- 已完成：设计 `trace_spans` 或统一 observability schema。
- 已完成：接入 router、memory、worker、tool、LLM、RAG、OCR/document parsing。
- 已完成：为 `/api/chat` 返回 compact latency summary。
- 已完成：写入数据库，便于后续分析慢阶段。

## 7. 调度者 Agent 与 Worker Agent 架构

状态：已完成调度者 Agent -> Worker Agent 多 Worker 执行闭环。

### 目标

- 架构应明确为调度者 Agent -> Worker Agent。
- 调度者负责：
  - 意图融合
  - 多意图规划
  - 状态管理
  - 工具权限判断
  - worker 调度
  - 结果合成
- Worker 负责各自领域任务，不反向承担全局调度。

### 当前状态

- `StudyAbroadOrchestrator` 承担调度者职责。
- `WorkerAgentSpec`、`WorkerContext`、`WorkerRunResult`、`WorkerRegistry` 已建立。
- 默认 worker registry 已覆盖：
  - Wellbeing
  - Travel
  - Finance
  - Fitness
  - Social Content
  - Task Planning
  - Email
  - Assignment
  - Notice Action
  - General Chat
- 每个 Worker 显式声明：
  - intent
  - input key
  - input schema
  - output artifact kind
  - required tools
  - missing information contract
  - memory namespaces
- LangGraph `dispatch_worker` node 根据 Router 输出选择 Worker。
- `MultiIntentExecutionPlanner` 已基于 Router structured intents 生成可执行计划，并进行：
  - agent_inputs 槽位补全。
  - 低置信 secondary intent 执行门控。
  - dependency / condition 保留。
- `AgentState` 已保存 `execution_plan` 与 `worker_execution_results`。
- LangGraph `dispatch_worker` node 已升级：
  - 单 intent 请求保持原单 Worker 路径。
  - 多 structured intents 请求进入多 Worker 执行路径。
  - 基于 step dependency 构建执行层；同一层无依赖 Worker 使用 `asyncio.gather` 并行执行。
  - 不同层之间按依赖顺序推进，依赖前序 artifacts 的 Worker 会等待前置 step 完成。
  - 并行 Worker 运行时只读取 `AgentState` 快照；Worker artifacts / missing information / next actions 由调度者按 step 顺序统一 merge 回全局 state。
  - 失败、blocked、needs_input 支持 partial result，不会让整个 graph 失控。
- `WorkerContext` 已注入：
  - execution_step
  - existing_artifacts
  - tool_statuses
  - tool_results
- graph 已统一读取 Worker `required_tools`，执行 tool availability 检查，并在提供显式 tool arguments 时通过 ToolExecutor 执行工具调用，将结果注入 WorkerContext 和调度者执行结果。
- 多 Worker 执行会输出 `multi_worker_execution_result` artifact，记录每个 step 的状态、worker intent、artifact_count、tool_statuses 和 tool_results。
- Worker span 已按 step 写入 latency summary / trace spans，例如 `worker.travel.step_0`。

### 缺口

- 当前已支持无依赖 Worker 同层并行；仍需保持依赖关系、artifact handoff 和审批边界。依赖前序结果的 Worker 不会并行抢跑。
- 未提供显式 tool arguments 时，graph 只注入 tool availability，不主动推断工具参数；避免调度者伪造工具调用意图。

### 收敛要求

- 已完成：定义 Worker Agent interface：
  - intent
  - input schema
  - output artifact type
  - required tools
  - missing information contract
  - memory namespaces
- 已完成：Orchestrator graph 根据 Router 输出选择 worker。
- 已完成：多意图执行 planner 输出可驱动多个 worker 按依赖分层执行；同层无依赖 Worker 支持并行。
- 已完成：工具状态和显式工具调用结果进入 worker 输入与调度者执行结果，不再只作为孤立 tool API。

## 建议收敛顺序

1. P0：架构纠偏：LangGraph 主链路 + Worker Agent interface。
2. P0：逐 Agent 迁移完整性审计。
3. P0：Travel 正式能力边界重设，禁止模板结果冒充真实查询。
4. P0：MCP/tool abstraction 与 provider availability。
5. P1：Travel Google Maps/Places/Directions + Weather 自动注入。
6. P1：Email provider：QQ / Outlook + approval send flow。
7. P1：Latency spans 入库与 trace summary。

## 当前结论

《阶段1缺陷分析总结.md》中提出的问题基本成立。当前项目已有大量结构和接口，但部分模块仍存在“文档标记已补齐，实际能力仍偏占位”的风险，尤其是：

- LangGraph 不是主编排入口。
- Travel Agent 已完成 Google Maps provider-informed planning、memory confirmation 和 Planner handoff 真实落库。
- Browser MCP live runtime 已接入；后续按实际 server 能力扩展 Browser 工具。
- 邮件发送未接入。
- 阶段耗时观测不完整。

后续开发应以本文档作为阶段 1 收敛基线，逐项补齐，不再用最小实现替代正式方案。
