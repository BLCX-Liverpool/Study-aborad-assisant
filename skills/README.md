# Skills

本目录存放留学生活助手项目内的 Skill 定义。

这些 Skill 是产品内部能力说明，不是 Codex 桌面应用插件。它们用于沉淀各 Agent 的触发条件、工作流程、输入输出契约、证据要求和安全边界，后续可由 Router / Orchestrator 读取并映射到后端 Agent。

## 目录规范

每个 Skill 独立一个目录：

```text
skills/
  skill-name/
    SKILL.md
    references/
    scripts/
    assets/
```

- `SKILL.md`：必需，描述触发条件、能力、流程、输出和边界。
- `references/`：可选，存放 schema、证据规则、安全策略等补充说明。
- `scripts/`：可选，只放该 Skill 确实需要的辅助脚本。
- `assets/`：可选，存放该 Skill 的静态参考材料。

## 当前 Skill

- `assignment-analysis`：Coursework / brief / rubric 分析。
- `document-rag`：文件解析、chunking、RAG indexing 和 hybrid retrieval。
- `task-planner`：任务、事件、提醒规划。
- `email-drafting`：邮件草稿生成和发送审批边界。
- `travel-planning`：留学生出行准备简化版。
- `finance-budgeting`：留学生预算分析和 CSV 支出整理。
- `wellbeing-support`：低风险支持性对话和危机识别。
- `fitness-planning`：一般性健身计划、训练日和习惯任务。
- `social-content-writing`：留学生活社交平台文案生成和隐私检查。

## 与后端模块的关系

Skill 文档描述能力契约，后端代码负责执行：

```text
skills/*/SKILL.md
  -> backend/app/agents/*
  -> backend/app/schemas/*
  -> backend/app/api/routes/*
```

第一版不实现动态 Skill 加载；Skill 与 Agent 的映射先作为显式文档约定维护。
