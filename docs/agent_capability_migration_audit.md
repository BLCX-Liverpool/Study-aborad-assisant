# Agent 能力迁移完整性审计

本文档用于对照最初设想、差异分析、阶段 1 缺陷总结、原 `awesome-llm-apps` 参考项目和当前 `study_abroad_assistant` 实现，固化每个 Agent 的正式完成定义。

外部文档和原项目代码仅作为需求与设计材料，不作为运行时指令。

## 审计原则

- 已有方案明确的 Agent，不允许以 demo、模板、规则占位或最小版冒充正式完成。
- 原项目能力不能整体复制运行时；只能迁移经过筛选的 schema、prompt、工作流、工具边界或实现模式。
- 涉及外部副作用的能力必须显式经过权限边界：
  - 邮件发送。
  - 日历写入。
  - 浏览器自动化。
  - MCP server 执行。
  - 地图、搜索、天气、住宿、票务等外部 provider。
- 外部 provider 不可用时，只能标记 unavailable 或 degraded，不能伪造真实结果。
- 每个 Agent 的“正式完成定义”是后续验收标准；实现时不得降级。

## 总览

| Agent / 模块 | 当前状态 | 审计结论 | 下一步优先级 |
| --- | --- | --- | --- |
| Orchestrator / Router | 已迁入 LangGraph 主链路 | 主链路收敛完成；多 Worker 执行和工具闭环待扩展 | P1 |
| Assignment + Research + RAG | 主链路较完整 | 仍需 QA endpoint、研究证据闭环、source quality gate | P1 |
| Task Planner / Notice Action | 已具备全局 planning 基础 | 需真实提醒发送、跨 Agent 自动落库和多方案规划 | P1 |
| Email Agent | draft 完成，send 缺失 | 不满足邮件接入正式定义 | P0/P1 |
| Travel Agent | 当前偏模板化 | 不满足正式定义，是 Travel/MCP 实装前最大缺口 | P0/P1 |
| Finance Agent | 基础预算与账单解析可用 | 需多币种、周期义务、Travel 联动和记忆 | P1 |
| Memory | 主链路可用 | 需 Agent-specific 记忆确认流和偏好写入闭环 | P1 |
| Wellbeing | 安全基础可用 | 需 LLM 二次安全分类、场景流程和地区资源 | P1/P2 |
| Fitness | 可生成计划 | 需真实 Task Planner 落地与进度反馈闭环 | P2 |
| Social Content | 文案可用 | 需平台知识库、品牌/素材输入和发布前审查 | P2 |
| Tool / MCP Layer | Tool registry 基础可用 | 缺 Browser MCP、Maps/Places/Directions、availability gate | P0/P1 |

## 1. Orchestrator / Router

### 参考来源

- 初始方案：统一调度者 Agent + Worker Agent。
- 阶段 1 缺陷总结：Agent 编排由 LangGraph 完成，FastAPI 负责后端服务。
- 当前实现：
  - `backend/app/agents/orchestrator/graph.py`
  - `backend/app/agents/orchestrator/workers.py`
  - `backend/app/agents/router/service.py`

### 当前实现

- `/api/chat` 已通过 `StudyAbroadOrchestrator.handle_chat()` 调用 LangGraph。
- Graph 节点覆盖：
  - initialize
  - route
  - memory
  - router observation
  - multi intent plan
  - worker dispatch
  - persist run
  - memory update
  - response build
- Router 已按方案使用 semantic vector + LLM classifier + voting fusion。
- Worker Agent interface 已建立。

### 缺口

- 多意图规划结果还没有驱动多个 Worker 顺序/并行执行。
- Worker `required_tools` 已声明，但 graph 尚未统一执行 tool availability check。
- Tool result 尚未作为标准上下文注入 Worker。

### 正式完成定义

- LangGraph 是唯一主编排入口。
- Router 使用正式融合策略，不退回单规则或单向量方案。
- Worker 只能通过 `WorkerAgent` 契约接入调度者。
- 多意图计划可以驱动多个 Worker，并保留依赖关系、跳过条件和失败策略。
- 工具调用结果进入 AgentState / WorkerContext，不作为孤立 API。

### 验收标准

- `/api/chat` 测试证明 `route_async()` 被 graph 调用。
- 每个 Worker 在 registry 中有 spec。
- trace 中可看到 router、memory、worker selected、worker completed、memory updated。
- 多意图样例能产生多个 worker step 或明确标记 waiting / unsupported。

## 2. Assignment + Research + RAG Agent

### 参考来源

- 原项目 Research Agent：triage -> research -> editor，事实收集和引用报告。
- ArXiv chat / Typed Agentic RAG：检索、引用、quote validation、低置信拒答。
- 当前实现：
  - Assignment analysis service。
  - DeepDoc 子进程 OCR。
  - Docling parse + chunking + BM25 + vector retrieval。
  - ArXiv / Web search / Paper retrieval / Idea verifier。

### 当前实现

- 已具备文件解析、OCR runtime、chunking、RAG indexing、hybrid retrieval。
- Assignment extractor + verifier 已可生成结构化作业分析。
- Research workflow 可生成 queries，并调用 ArXiv / Web provider。
- Research source 可入 RAG index。
- Idea verifier 支持 LLM verifier 与规则回退。

### 缺口

- 没有面向用户的 Assignment QA 主工作流。
- Research workflow 与 Assignment 分析、RAG index、idea verifier 还不是一个完整闭环。
- 引用验证还未达到 typed RAG 的“exact quote validation”强度。
- 检索失败、证据不足、source 质量不足时的拒答/降级策略需要更明确。
- Research report / source synthesis 还不完整。

### 正式完成定义

- 用户上传 coursework / brief 后，系统能完成：
  - parse + OCR
  - requirement extraction
  - evidence verification
  - research query generation
  - source search
  - selected source indexing
  - assignment-grounded QA
  - idea verification
- 所有结论必须能追溯到 document chunk 或 research source。
- 证据不足时必须返回 insufficient evidence，而不是编造。

### 验收标准

- 扫描 PDF 能触发 DeepDoc OCR 并进入 chunk。
- Research source 写入后能被 `research_only` retrieval 命中。
- QA 输出包含 citation / chunk id / source metadata。
- 低分检索返回拒答或要求补充材料。

## 3. Task Planner + Notice Action Agent

### 参考来源

- 初始方案：通知、邮件、账单、租房信、航班确认自动转 ActionItem，并进入全局 Planner。
- 当前实现：
  - NoticeActionParser LLM-first + rules fallback。
  - GlobalPlanner。
  - ReminderScheduler。
  - Reminder worker draft queue。

### 当前实现

- Notice parser 已支持多 action item。
- Global planner 可从 action items 生成 tasks / events。
- Assignment planner 可生成分阶段任务。
- Reminder drafts 和 email queue draft 已存在。
- Chat 链路可从 Notice -> Planner。

### 缺口

- 邮件提醒只是 draft queue，没有真实发送。
- Planner output 不一定自动写入 repository，需要按 API/worker 路径确认。
- 多方案规划、冲突 resolution、existing tasks/events 的自动加载还需要增强。
- Calendar provider 已决定不做强依赖，但 email reminder 需要真实发送链路。

### 正式完成定义

- 所有 Agent 可输出标准 ActionItem / PlanningItem。
- Global Planner 能读取已有 tasks/events/reminders 和 memory preferences。
- Planner 能生成任务、事件、提醒，并按权限写入数据库。
- Reminder worker 能在用户批准后通过 Email Provider 发送提醒。

### 验收标准

- Notice 文本可生成 action items、planner output、DB tasks/reminders。
- 已存在事件会触发 conflict findings。
- due reminder 能进入 email send approval flow。
- 发送后 reminder status 更新。

## 4. Email Agent

### 参考来源

- 初始方案：邮件回复、邮件草稿、通过邮件发送提醒。
- 阶段 1 缺陷总结：QQ 邮箱和 Outlook 邮箱接入。
- 当前实现：
  - Email draft generator。
  - Recipient classifier。
  - Style policy。
  - Approval gate。
  - Email Provider interface。
  - dry-run provider。
  - QQ SMTP provider。
  - Outlook SMTP + STARTTLS provider。
  - send audit table / repository。
  - Reminder worker approval send flow。

### 当前实现

- 可生成邮件草稿。
- 可判断发送需要用户审批。
- 支持 draft -> approval -> send 状态流。
- 支持 `/api/email/providers/status` 检查 provider availability。
- 支持 `/api/email/send` 在批准后发送并写入审计。
- 支持 `/api/planner/reminders/email-send` 发送已到期 email reminders。

### 缺口

- Outlook 当前采用 SMTP + STARTTLS；如需 Microsoft Graph/OAuth，需要后续补 token 管理。
- 自动 retry worker 尚未实现，但失败原因和 send audit 已落库。

### 正式完成定义

- Email Agent 不是只生成 draft，而是支持完整但受控的邮件生命周期：
  - draft
  - user approval
  - provider send
  - send result audit
  - retry / failure reason
- QQ 邮箱和 Outlook 必须通过统一 provider interface 接入。
- 任何发送动作必须显式 approval。

### 验收标准

- dry-run provider 可在测试中模拟发送。
- QQ/Outlook provider availability 可被检查。
- 未批准时发送 API 返回 requires_approval。
- 已批准时记录 send attempt 和 status。
- Reminder worker 可把 due email reminder 交给 provider。

## 5. Travel Agent

### 参考来源

- Starter Travel Agent：researcher + planner，基于搜索生成 itinerary。
- Travel Agent with Memory：记住旅行偏好。
- MCP Travel Planner：Google Maps / Airbnb / Google Search，路线、地点、住宿、天气、成本。
- 当前实现：
  - Checklist。
  - 模板 itinerary。
  - LocalRouteProvider 固定估算。
  - Weather tool 存在但未自动注入。

### 当前实现

- 可输出 checklist、required documents、budget notes、risk notes。
- `TravelItineraryGenerator` 支持多日结构、weather 输入、budget breakdown、planner items。
- 主 `TravelAgentService` 已完成正式边界重设：
  - 输出 `route_suggestions`
  - 输出 `place_suggestions`
  - 输出 `weather_forecasts`
  - 输出 `budget_breakdown`
  - 输出 `information_sources`
  - 输出 `tool_statuses`
  - 输出 `memory_candidates`
- 路线本地估算已显式标记为 `source=estimated`，不再伪装成 provider route。
- Google Maps Directions / Places 已接入 live provider client：
  - `travel.maps.directions` 调用 Google Directions API。
  - `travel.maps.places` 调用 Google Places Text Search。
  - 缺少 API key 或 provider 调用失败时返回 unavailable / degraded，不生成伪真实数据。
- 多日 itinerary 已升级为 provider-informed：
  - 首日/返程 travel block 使用 provider route duration / distance。
  - 中间活动和 local orientation 优先引用 Places 结果。
  - 预算 `estimate_basis` 会记录是否使用 Google Maps route context。
- Travel -> Task Planner handoff 已接入真实落库：
  - 未确认时返回 `needs_confirmation`。
  - 确认后写入 tasks / events / reminders。
- Travel memory confirmation flow 已接入：
  - 可写入 pending travel memory candidates。
  - 未确认 candidate 不进入长期记忆检索。
  - 确认后转换为正式 `user_preference`。

### 缺口

- Google Maps provider 已接入，但仍需要生产环境配置 `GOOGLE_MAPS_API_KEY` 并验证对应 API 权限。
- 天气已支持在 async plan 中自动调用，多日 itinerary 可消费外部传入 weather forecasts；下一步可让 `/api/travel/itinerary` 自动拉天气。
- provider 可用时路线/地点已 provider-informed；provider 不可用时路线耗时仍回退为显式 `estimated`。
- 预算分解仍是比例模型，但会记录 route provider context；住宿/票价/餐饮价格 provider 尚未接入。
- 更细粒度旅行偏好读取仍可增强，例如饮食禁忌、住宿偏好、出行节奏、常用出发地的结构化抽取。

### 正式完成定义

- Travel Agent 必须是 provider/tool-informed planner，而不是模板 checklist。
- 输出必须区分：
  - user provided
  - provider verified
  - estimated
  - unavailable
- 必须自动尝试获取：
  - weather
  - route / transit duration
  - places / activities
  - local practical constraints
- 多日 itinerary 必须由真实或可追溯数据约束。
- 不做订票、不付款、不提交外部表单；只做建议和 approval boundary。

### 验收标准

- provider 不可用时输出 `tool_status=unavailable`，不生成伪真实路线。
- provider 可用时 route suggestions 包含 source、duration、distance 或 place id。
- itinerary days 引用 place/route/weather source。
- budget item 有 estimate basis。
- travel preferences 从 memory namespace 读取，并输出 memory candidates。

## 6. Finance Agent

### 参考来源

- Financial Coach Agent：预算分析、储蓄策略、结构化财务输出。
- xAI Finance Agent：实时金融数据和 web search，但当前项目不能做投资建议。
- 当前实现：
  - CSV expense parser。
  - StudentBudgetAnalyzer。
  - Bill parser + verifier。
  - Budget goals。

### 当前实现

- 支持基础预算分析。
- 支持账单文本/文件解析。
- 支持预算目标 review。
- 不提供金融、税务、法律建议。

### 缺口

- 多币种汇率未接入。
- 学费分期、押金、房租周期、固定账单周期仍不完整。
- recurring expense 与真实日程/提醒联动不足。
- Travel budget handoff 不完整。
- finance memory namespace 的读取/确认不完整。

### 正式完成定义

- Finance Agent 面向留学生现金流，而不是投资分析。
- 支持账单、租房、学费、生活费、旅行预算、兼职收入、汇率估算。
- 能把 upcoming obligations 转为 planner items。
- 明确风险边界：不做投资/税务/法律建议。

### 验收标准

- 账单文件能解析出 obligation、amount、due date、evidence。
- recurring expenses 能生成 future obligations。
- travel budget 可进入 Finance output。
- exchange rate provider 不可用时明确标记 stale/unavailable。

## 7. Memory Agent / Memory Service

### 参考来源

- Travel Agent with Memory：用户偏好和历史交互。
- 初始方案：跨 Agent 长期状态理解。
- 当前实现：
  - short-term memory。
  - long-term memory repository。
  - namespace routing。
  - topic continuity。
  - query rewrite。
  - sensitivity policy。

### 当前实现

- Chat 主链路已接入 MemoryManager。
- 支持短期上下文、长期检索、压缩、topic continuity、query rewrite。
- Wellbeing 默认不写敏感长期记忆。

### 缺口

- Agent-specific memory candidates 未统一进入确认流。
- Travel / Finance / Fitness / Social 等偏好未形成标准写入路径。
- Memory UI / review / delete 未完成。
- Memory 与 WorkerContext 的强绑定仍有限。

### 正式完成定义

- 每个 Agent 明确可读 memory namespace 和可写 memory candidate。
- 长期记忆必须经过 sensitivity + confirmation policy。
- 用户能查看、确认、拒绝或删除候选记忆。
- Worker 执行时能收到相关 memory context。

### 验收标准

- Travel 偏好、Finance 预算、Fitness 目标能作为 candidate 输出。
- 未确认敏感信息不写入长期记忆。
- query rewrite 后重新路由且 trace 可见。
- memory access 可审计。

## 8. Wellbeing Agent

### 参考来源

- Mental Wellbeing / Breakup Recovery Agent：assessment、action plan、follow-up。
- 当前实现：
  - safety layer。
  - crisis/high/medium/low response。
  - professional notice。

### 当前实现

- 支持危机识别和保守升级。
- 不诊断，不替代专业帮助。
- 默认不保存敏感内容。

### 缺口

- 风险识别主要偏规则。
- 没有 LLM safety classifier 二次判定。
- 没有 homesickness、loneliness、culture adaptation、study stress 等子场景流程。
- 没有地区/学校资源配置。
- 没有 follow-up task handoff。

### 正式完成定义

- Wellbeing Agent 必须安全优先。
- 风险分类要有规则 + LLM 二次判定，但高风险保守升级。
- 子场景支持必须落到具体行动建议和可选 planner handoff。
- 危机资源不能硬编码成不准确内容；需按地区/学校配置或明确建议联系本地紧急服务。

### 验收标准

- 高风险输入触发 crisis guidance。
- 中低风险输入能分类到具体场景并给行动计划。
- 任何诊断/治疗请求被安全边界拦截。
- 敏感记忆不会默认保存。

## 9. Fitness Agent

### 参考来源

- Health and Fitness Agent：profile、目标、基础健身/饮食 prompt。
- 当前实现：
  - Fitness plan。
  - schedule tasks。
  - progression。
  - memory candidates。

### 当前实现

- 可根据目标、可用时间、器械生成训练计划。
- 输出渐进策略和风险提示。
- 输出可交给 planner 的 schedule tasks。

### 缺口

- schedule tasks 未确认真实写入 Task Planner。
- 缺少进度反馈和计划调整闭环。
- 没有健康数据 provider；也不应该做医疗判断。
- 饮食建议边界未完整建模。

### 正式完成定义

- Fitness Agent 提供可执行但非医疗的计划。
- 计划能进入 Task Planner。
- 支持用户反馈后的周计划调整。
- 偏好和限制进入 memory candidate 确认流。

### 验收标准

- 输出 schedule tasks 可被 planner 落库。
- 输入 injury/health constraint 时降强度并提示专业建议。
- 反馈“太难/太轻松/没时间”能重新生成调整方案。

## 10. Social Content Agent

### 参考来源

- Journalist Agent：search -> write -> edit。
- 初始迁移方向：Social Content Agent。
- 当前实现：
  - platform classifier。
  - platform standards。
  - copy generator。
  - LLM generator fallback。
  - privacy checker。

### 当前实现

- 可生成多平台文案候选。
- 有基本隐私检查。
- 图片生成只输出设计边界，不执行。

### 缺口

- 没有外部素材/品牌资料接入。
- 平台规范较轻，未形成 references 级知识库。
- 没有 search/research -> write -> edit 三阶段闭环。
- 没有发布前 checklist 和版本对比。

### 正式完成定义

- Social Content Agent 第一阶段只做文案。
- 必须执行 platform fit、privacy review、tone/style review。
- 需要多版本候选和编辑理由。
- 图片生成必须走独立 tool，不混入文案 Agent。

### 验收标准

- 小红书/朋友圈/Instagram/LinkedIn 输出不同结构和语气。
- 包含 privacy risk result。
- blocking input 不生成文案。
- 输出可解释每个版本的适用场景。

## 11. Tool / MCP Layer

### 参考来源

- Multi-MCP Agent Router：router -> specialist -> MCP server。
- Browser MCP Agent：Playwright 浏览器控制、网页抽取、截图。
- MCP Travel Planner：Google Maps / Airbnb / Search。
- 当前实现：
  - ToolRegistry。
  - ToolExecutor。
  - Weather / ArXiv / Web / Reminder / Calendar draft tools。

### 当前实现

- 基础 tool registry 和 permission executor 存在。
- Weather provider 使用 Open-Meteo。
- Research web/arxiv tool 已封装。
- Reminder/calendar 仍是 draft。
- 已新增正式 provider availability schema。
- 已新增 `/api/tools/status`。
- 已新增 Browser MCP live adapter：
  - `browser.mcp.search_extract`
  - 支持 HTTP JSON-RPC endpoint。
  - 支持 stdio MCP server command。
- 已新增 Google Maps adapter boundaries：
  - `travel.maps.directions`
  - `travel.maps.places`
- 当前 Browser MCP adapter 在未配置或 provider 调用失败时返回 unavailable / degraded，不伪造结果。
- Google Maps Directions / Places adapter 已启用 live HTTP client；未配置 API key 或 provider 调用失败时返回 unavailable / degraded。

### 缺口

- Browser MCP 的具体浏览能力取决于连接的 MCP server 暴露的工具。
- tool result 未统一进入 LangGraph WorkerContext。

### 正式完成定义

- Tool / MCP layer 必须统一抽象：
  - name
  - capability
  - required env
  - permission level
  - availability status
  - run result
  - recoverable error
- Browser/Maps 等外部工具不可用时不能伪造结果。
- Agent 通过 tool spec 声明依赖，Orchestrator graph 负责检查和注入结果。

### 验收标准

- tool availability endpoint 可列出 provider 状态。
- 未配置 Google Maps API key 时 Travel Agent 明确 degraded。
- Browser MCP 未启动时 web extraction 返回 unavailable；provider 出错时返回 degraded。
- tool result 写入 trace/tool log 并可进入 WorkerContext。

## 12. Email / Reminder / Calendar 边界

### 当前决策

- 不强依赖 Calendar provider。
- Reminder 可通过邮件发送。
- Calendar draft 可保留为本地 draft，不写外部日历。

### 正式完成定义

- Email reminder 是正式发送能力，不是永久 draft。
- Calendar action 默认生成 local draft 或 planner task。
- 所有外部发送/写入都需要 approval。

### 验收标准

- Reminder due -> email approval -> provider send -> status update。
- Calendar intent -> local task/event draft，不调用外部 Calendar。
- 外部发送失败保留 error 和 retry metadata。

## 后续收敛顺序

1. 已完成：Travel 正式能力边界重设，补充 source / confidence / tool_status，禁止模板结果冒充真实查询。
2. 已完成：Tool / MCP provider abstraction，先落 availability 与统一 run result。
3. 已完成：Travel 接入 Weather 自动调用与 Maps/Places/Directions provider。
4. P1：Email Provider interface + dry-run provider + send audit。
5. P1：QQ SMTP / Outlook provider。
6. P1：Memory candidate confirmation flow。
7. P1：Assignment QA + citation/quote validation。

## 当前审计结论

当前项目的核心架构已经进入正式形态，尤其是 Router、LangGraph 主链路、Worker interface、文档解析/RAG、Memory 与基础 tool registry。

但以下模块不能标记为正式完成：

- Travel Agent：已完成 provider-informed 收敛、memory confirmation 和 Planner 真实落库；票价/开放时间 provider 仍需强化。
- Email send / reminder send：已完成 provider + approval send flow；自动 retry worker 可后续增强。
- Browser MCP provider：已接入 live runtime，后续按具体 server 能力扩展工具语义。
- Agent-specific memory candidates：输出不统一，确认流不完整。
- Assignment QA 和 evidence quote validation：仍需强化。

后续实现必须按本审计文档的完成定义验收。
