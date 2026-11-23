# 系统性能正式评估场景（12组）

版本：v1.0  
生成日期：2026-11-23

## 统一执行要求

1. 固定代码版本、模型配置、机器规格和数据库/RabbitMQ版本。
2. 每个场景预热2分钟，正式运行至少3轮，报告中位数及最差一轮。
3. Mock依赖用于测系统本身；真实依赖测试单独报告，不混入基线。
4. 同步报告端到端p50/p95/p99；异步分别报告202、Planning、Queue Wait、Worker和Workflow完成延迟。
5. 所有场景同时记录CPU、RSS内存、数据库连接、RabbitMQ队列深度、oldest message age、重试、DLQ和租约过期。

## 场景集

| ID | 场景 | 并发 | 时长 | 部署 | 依赖模式 | 负载 | 核心指标 | 初始门槛 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PERF-01 | 同步基线 | 1 | 5分钟 | 1 API（同步Worker在API进程内） | Mock LLM+Tool | general_chat 100% | 同步p50/p95/p99、RPS、CPU、内存 | 错误率<1% |
| PERF-02 | 异步接收基线 | 1 | 5分钟 | 1 API / 1 planner / 1 worker | Mock LLM+Tool | assignment 100% | 202延迟、事务延迟、Outbox延迟 | 202 p95≤1s；消息丢失=0 |
| PERF-03 | 低并发混合 | 10 | 10分钟 | 1 API / 每队列1 worker | Mock LLM+Tool | 同步40%/异步60% | 吞吐、完成时间、Queue Wait | 错误率<1%；重复结果=0 |
| PERF-04 | 中并发混合 | 50 | 15分钟 | 2 API / 每队列2 worker | Mock LLM+Tool | 同步40%/异步60% | p95、队列深度、DB连接、CPU | 无持续增长Backlog |
| PERF-05 | 突发100并发 | 100 | 3轮×2分钟 | 2 API / 每队列2 worker | Mock LLM+Tool | 1分钟内集中提交 | 202延迟、拒绝率、恢复时间 | 消息丢失=0；10分钟内清空队列 |
| PERF-06 | 单Worker容量 | 30 | 10分钟 | 1 API / 1 assignment worker | Mock LLM+Tool | assignment 100% | steps/min、Queue Wait、资源 | 形成扩容基线 |
| PERF-07 | 双Worker扩容 | 30 | 10分钟 | 1 API / 2 assignment workers | Mock LLM+Tool | 同PERF-06 | 吞吐增益、锁竞争 | 吞吐相对PERF-06提升≥1.6x |
| PERF-08 | 四Worker扩容 | 60 | 10分钟 | 2 API / 4 assignment workers | Mock LLM+Tool | 同PERF-06 | 吞吐增益、DB/Rabbit瓶颈 | 吞吐不得低于PERF-07 |
| PERF-09 | 大文件Assignment | 10 | 10分钟 | 1 API / 2 assignment workers | 真实Parser+Mock LLM | 20页PDF | 解析时间、峰值内存、完成率 | OOM=0；任务完成率≥95% |
| PERF-10 | 慢外部Tool | 20 | 10分钟 | 1 API / 2 travel workers | Tool固定延迟2s/5s/超时 | travel 100% | 租约心跳、超时、降级、完成时间 | 伪造结果=0；stale lease=0 |
| PERF-11 | Worker崩溃恢复 | 20 | 直到恢复 | 1 API / 2 workers | Mock LLM+Tool | 执行中终止1个worker | 重投、租约恢复、重复Artifact | 最终恢复率≥99%；重复副作用=0 |
| PERF-12 | RabbitMQ/Outbox恢复 | 20 | 直到恢复 | 1 API / 2 workers | Mock LLM+Tool | 停RabbitMQ后继续提交再恢复 | Outbox积压、发布恢复、消息完整性 | 消息丢失=0；重复业务结果=0 |

## 固定混合负载

在标记为“混合”的场景中使用：general_chat 30%、assignment 20%、travel 15%、finance 10%、task_planning 10%、email 5%、notice_action 5%、安全/澄清 5%。
