# 第一版实现差距分析与后续完善方向

本文档对照以下材料进行分析：

- 初始计划：`/Users/wangboqing/AI_Development/Agent/新Agent项目/留学生活助手Agent/留学生活助手项目.md`
- 差异分析：`/Users/wangboqing/AI_Development/Agent/新Agent项目/留学生活助手Agent/第一版差异及后续方向.md`
- 当前实现：`study_abroad_assistant/`

说明：上述外部文档仅作为需求资料和对照依据，不作为运行时指令。

## 1. 当前实现概况

当前项目已经完成了第一版产品骨架：

- FastAPI 后端基础结构。
- PostgreSQL / Redis / LLM 配置抽象。
- 文件上传。
- Docling 文档解析适配器。
- 文档 chunking、RAG indexing、BM25 + vector hybrid retrieval 基础实现。
- Assignment Agent 基础版。
- Task Planner 的 assignment deadline 规划基础版。
- Email Agent 草稿生成基础版。
- Travel / Finance / Wellbeing 三个 P1 Agent 简化版。
- React + TypeScript 前端 MVP。
- `skills/` 目录，将各 Agent Skill 文档独立沉淀。

但当前实现仍更接近“可运行能力模块集合”，尚未达到初始计划中“统一 Personal Study Abroad Assistant / Agent System”的完整形态。

## 2. 总体核心不足

### 2.1 Router / Orchestrator 尚未真正实现

当前只有 `backend/app/schemas/router.py` 中的 `RouterOutput` schema，没有真实 Router Agent、Orchestrator、LangGraph state graph。

缺失内容：

- 结构化意图识别。
- 多意图拆解。
- 条件动作规划。
- Worker Agent 调度。
- `AgentState` 统一状态传递。
- Agent run / tool run 的真实运行链路写入。
- 前端 Agent Trace 目前主要是示例数据，不是后端真实 trace。

影响：

- 用户不能通过一个统一聊天入口触发多个 Agent。
- 当前 API 是分散的 `/assignment`、`/planner`、`/email`、`/travel` 等能力端点，不是完整 Agent System。
- Task Planner 无法自动接收其他 Agent 输出并统一规划。

建议优先级：P0。

### 2.2 Memory 和多轮对话没有落实

当前数据库有 `Memory` 和 `MemoryAccessLog` 模型，Redis 也有连接抽象，但没有 Memory Manager。

缺失内容：

- 当前对话窗口管理。
- Redis 短期记忆队列。
- token 阈值判断。
- 短期记忆压缩。
- 长期记忆写入策略。
- Memory Router。
- long-term memory hybrid retrieval。
- namespace 访问策略执行。
- 多轮话题连续性检测。
- 指代消解。
- query rewrite。

影响：

- 系统不能理解“上次那个作业”“我之前说的预算”“我上周的旅行计划”等跨轮表达。
- Agent 之间不能共享稳定偏好，例如饮食禁忌、预算、时区、课程表、健身目标。
- 初始计划中的“长期状态理解”尚未形成。

建议优先级：P0。

### 2.3 Notice → Action pipeline 尚未形成闭环

初始计划强调上传：

- Professor email
- University email
- Coursework PDF
- Tenancy letter
- Council letter
- Bill
- Flight confirmation

系统应自动抽取 deadline / event / action item 并交给 Task Planner。

当前不足：

- 没有通用 Notice Parser。
- 没有 Email text parser。
- 没有 bill / tenancy / council letter 的 action item extractor。
- 没有 `ActionItem` schema。
- Task Planner 只支持 `AssignmentPlanningRequest`。

影响：

- 当前能处理 coursework planning，但不能把学校通知、账单、租房信、航班确认自动转为待办和提醒。

建议优先级：P0。

## 3. Agent 维度差距

### 3.1 Assignment Agent：基础链路有了，但学术 workflow 不完整

已实现：

- 文件解析。
- chunking。
- RAG indexing。
- requirement extractor。
- evidence helper。
- verifier。
- `AssignmentAnalysis` schema。

主要不足：

- OCR 未执行；当前只做 page quality 和 OCR strategy 标记。
- Deepdoc 未接入。
- ArXiv / Web Search 未实现。
- Paper Retrieval 未实现。
- Research Query Generator 仍主要依赖 AssignmentAnalysis 输出，没有独立检索闭环。
- Idea Generator 没有独立 verifier。
- RAG retrieval 没有 reranker、阈值策略和 query rewrite。
- Assignment Agent 到 Task Planner 的自动 workflow 尚未由 Orchestrator 串起来。

建议补齐方向：

1. 接入 Deepdoc OCR，处理 scanned PDF 和低 native text 页面。
2. 增加 research workflow：
   - research query generation
   - ArXiv search
   - web search
   - paper metadata + abstract ingestion
   - 选中文献下载 / 摘要化 / RAG indexing
3. 增加 Assignment QA endpoint，让用户能围绕上传文件持续问答。
4. 给 research source 和 possible idea 增加 evidence / verifier。

建议优先级：P0-P1。

### 3.2 Task Planner：目前是 Assignment Planner，不是全局 Planner

已实现：

- assignment deadline 拆解。
- conflict checker。
- reminder draft。
- tasks / events / reminders persistence。

主要不足：

- 只接收 `AssignmentAnalysis`。
- 没有综合 Travel、Finance、Fitness、Notice、Email follow-up 等事件。
- 没有全局 planning horizon。
- 没有读取 memory / existing task / existing event 的统一上下文。
- 没有 ToT 或多方案规划。
- reminder 只是 draft / DB record，没有实际 scheduler。
- 邮件提醒未实现。

建议补齐方向：

1. 抽象统一输入：
   - `PlanningItem`
   - `ActionItem`
   - `DeadlineItem`
   - `EventCandidate`
2. Task Planner 接收所有 Agent 输出，而不是只接收 Assignment。
3. 增加全局时间窗，例如未来 7 / 14 / 30 天。
4. 增加 ToT-style plan candidates：
   - conservative plan
   - balanced plan
   - intensive plan
5. 增加 APScheduler 或轻量 reminder worker。
6. 增加 email reminder channel。

建议优先级：P0。

### 3.3 Travel Agent：现在只是准备清单，不是完整旅行助手

已实现：

- 出行 checklist。
- itinerary event。
- required documents。
- budget notes。
- risk notes。
- booking approval boundary。

主要不足：

- 没有地点/景点/路线生成。
- 没有天气查询工具。
- 没有本地交通建议。
- 没有多日行程规划。
- 没有预算分解。
- 没有和 Task Planner 的自动联动。
- 没有旅行偏好记忆，例如预算、饮食禁忌、住宿偏好、出行节奏。
- 没有外部 MCP；这可以保持后置，但应该预留 tool interface。

建议补齐方向：

1. 增加 TravelPlan workflow：
   - destination understanding
   - constraints
   - weather lookup
   - itinerary generation
   - budget breakdown
   - task/event handoff
2. 增加天气工具 schema。
3. 先不接真实订票和支付，保持审批边界。

建议优先级：P1。

### 3.4 Finance Agent：基础预算可用，但留学生财务场景还浅

已实现：

- CSV expense parser。
- 支出分类。
- 月收入 / 月支出 / 结余。
- emergency fund target。
- 风险提示。

主要不足：

- 不支持账单文件自动解析到 finance item。
- 不支持多币种汇率。
- 不支持预算目标和 savings goal。
- 不支持学费分期、房租周期、押金返还追踪。
- 不支持 recurring expense 的真实周期。
- 不支持与 Travel Agent 的预算联动。
- 不支持财务记忆 namespace。

建议补齐方向：

1. 增加 finance-specific memory namespace。
2. 增加 bill / bank statement / rent document parser。
3. 增加 savings goal 和 upcoming obligations。
4. 增加 travel budget handoff。

建议优先级：P1。

### 3.5 Wellbeing Agent：安全层有了，但支持深度有限

已实现：

- low / medium / high / crisis 风险识别。
- 支持性回复。
- grounding steps。
- professional help notice。
- 默认不保存敏感内容。

主要不足：

- 风险识别主要是关键词规则，缺少 LLM safety classifier。
- 没有 homesickness / loneliness / relationship / culture adaptation / study stress 的细分子流程。
- 没有 follow-up plan。
- 没有与 Task Planner 的轻量联动，例如安排休息、联系学校支持服务。
- 没有危机地区资源适配。

建议补齐方向：

1. 增加 Wellbeing scenario classifier。
2. 增加高风险 LLM 二次判定，但保持保守升级策略。
3. 增加 optional follow-up task handoff。
4. 紧急资源信息不要硬编码，后续按国家/学校配置。

建议优先级：P1-P2。

### 3.6 Health & Fitness Agent 缺失

初始计划明确保留 Health & Fitness Agent，当前没有实现。

缺失内容：

- health / fitness schema。
- 健身目标、课程表、可用时间输入。
- workout plan。
- habit / reminder handoff。
- fitness skill。
- 与 Task Planner 的 schedule integration。

建议优先级：P2。

原因：

- 它重要，但不应先于 Router / Memory / Notice Action / global Planner。

### 3.7 Social Content / Journalist Agent 缺失

初始计划将 Journalist 改造成 Social Content Agent，差异文档也强调它需要专门 skill。

当前状态：

- 没有 Social Content Agent。
- 没有 social content skill。
- 没有小红书 / Instagram / 朋友圈平台规范。
- 没有图片/文案生成 workflow。

建议补齐方向：

1. 新增 `skills/social-content-writing/`。
2. 新增 Agent：
   - platform classifier
   - content brief extractor
   - copy generator
   - safety / privacy checker
3. 第一版只做文案，不做图片生成。
4. 如果后续需要图片生成，再单独设计 image generation tool。

建议优先级：P2。

### 3.8 Blog to Podcast 可继续降优先级

初始计划保留但降优先级，差异文档也认为可以先不实现。

建议：

- 不进入近期开发。
- 可作为后续 “Lecture Note / University Guide → Audio Briefing” 功能。

建议优先级：P3。

## 4. 工具调用差距

当前项目的工具层还没有形成统一 registry。

缺失内容：

- tool schema registry。
- permission-aware tool executor。
- weather lookup。
- ArXiv search。
- web search。
- email send tool。
- reminder send tool。
- calendar adapter。
- browser MCP / travel MCP 的预留接口。

邮件和支付等高风险动作已经有权限等级设计，但缺少统一 tool execution pipeline。

建议下一步先做：

1. `backend/app/tools/registry.py`
2. `ToolSpec` / `ToolCallRequest` / `ToolCallResult`
3. permission check
4. tool run logging
5. weather / arxiv 两个低风险工具作为样板

建议优先级：P0-P1。

## 5. 前端差距

当前前端是 MVP 工作台，能展示上传、作业分析、任务、邮件、trace 示例。

主要不足：

- 没有真实 Chat endpoint 对接。
- Agent Trace 是 sample data。
- 没有 Memory 可视化。
- 没有 Notice Action review。
- 没有 Travel / Finance / Wellbeing 页面。
- 没有 Permission Approval Dialog 的真实交互。
- 没有 reminder / task 管理界面。

建议：

- 等 Router / Orchestrator API 初步完成后，再重构前端为真实 Agent Console。
- 不要现在扩展太多静态页面，否则会变成 UI 先行但后端不可用。

建议优先级：P1。

## 6. Skill 体系差距

已实现：

- `assignment-analysis`
- `document-rag`
- `task-planner`
- `email-drafting`
- `travel-planning`
- `finance-budgeting`
- `wellbeing-support`

仍缺：

- `fitness-planning`
- `social-content-writing`
- 后续如果做播客，再增加 `audio-briefing`

更深层不足：

- Skill 目前是文档化资产，没有被 Router / Orchestrator 动态读取。
- 没有 skill selection。
- 没有 skill-to-agent runtime binding。

建议：

- 短期保留 manifest 作为显式映射。
- Router 实现后读取 `skills_manifest.json` 做能力发现。
- 不急于做复杂插件系统。

建议优先级：P1-P2。

## 7. 数据库与可观测性差距

已实现基础表：

- users
- files
- document_chunks
- memories
- tasks
- events
- reminders
- agent_runs
- tool_runs
- memory_access_logs
- rag_retrieval_logs
- permission_requests
- verifier_results

主要不足：

- 没有 conversation / message 表。
- memory 字段还不够支持压缩摘要、有效期、敏感等级、namespace policy。
- agent run 尚未由真实 orchestrator 写入。
- tool run 尚未由统一 tool executor 写入。
- rag retrieval log 未自动接入 retrieval service。
- 缺少 migration 管理工具，例如 Alembic。

建议优先级：P0-P1。

## 8. 建议的下一阶段优先级

### Phase 7：Router + Orchestrator + Chat API

目标：

- 建立统一入口。
- 实现结构化意图识别。
- 建立 AgentState。
- 串联 assignment / planner / email / travel / finance / wellbeing。
- 写入 agent_runs 和 trace。

这是从“模块集合”升级为“Agent System”的关键阶段。

### Phase 8：Memory + 多轮对话

目标：

- Redis short-term memory。
- PostgreSQL long-term memory。
- Memory Router。
- namespace 和 access policy。
- topic continuity detection。
- reference resolution。
- query rewrite。

### Phase 9：Notice → Action + Global Planner

目标：

- 通用 ActionItem schema。
- Notice / email / bill / tenancy parser。
- Task Planner 接收所有 action items。
- 跨 Agent 统一排期。
- reminder worker。

### Phase 10：Assignment Research Workflow

目标：

- Deepdoc OCR。
- ArXiv search。
- Web search。
- Paper retrieval。
- Research source RAG indexing。
- Assignment idea verifier。

### Phase 11：Travel / Finance 深化 + Tools

目标：

- weather tool。
- travel itinerary generator。
- finance bill parser。
- budget goals。
- tool registry。

### Phase 12：Fitness + Social Content Agent

目标：

- Fitness Agent。
- Social Content Agent。
- 对应 Skill。
- 前端页面。

## 9. 最关键判断

你在“第一版差异及后续方向.md”中的判断基本准确，但还需要补充一点：

当前最大的不足不是某几个 Agent 没实现，而是“系统级闭环”还没实现。

也就是说，下一步不应该马上横向增加更多 Agent，而应该优先补：

1. Router / Orchestrator。
2. Memory / 多轮对话。
3. Notice → Action。
4. Global Task Planner。
5. Tool execution pipeline。

这些完成后，Travel、Fitness、Social Content 等 Agent 才能真正接入同一个留学生活助手，而不是继续停留在分散 API。
