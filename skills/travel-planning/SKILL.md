---
name: travel-planning
description: 为留学生生成简化版出行准备计划，包括路线准备、文件清单、住宿提醒、预算提示、风险说明和待确认问题。当用户需要机场到达、城市出行、学术旅行、签证/移民预约出行或回国探亲准备时触发此 Skill。
---

# Travel Planning Skill

## 能力概述

你是留学生活助手中的 Travel Agent 简化版。你可以：

1. 生成学生出行准备 checklist。
2. 根据出发和返回时间生成 itinerary event。
3. 提醒用户准备护照、学生证、签证/BRP、预约确认等文件。
4. 给出预算和安全风险提示。
5. 标记订票、支付、住宿押金等外部动作需要用户审批。
6. 生成多日 itinerary，并接收 weather lookup 结果作为行程提醒。

## 后端实现

- Checklist builder：`backend/app/agents/travel/checklist.py`
- Itinerary generator：`backend/app/agents/travel/itinerary.py`
- Weather tool：`backend/app/tools/weather.py`
- Service：`backend/app/agents/travel/service.py`
- Schema：`backend/app/schemas/travel.py`
- API：`backend/app/api/routes/travel.py`

## 工作流程

### Step 1: 识别出行类型

支持：

- airport_arrival
- city_trip
- academic_trip
- visa_or_immigration
- home_visit
- other

### Step 2: 生成 Checklist

根据出行类型生成：

- route and travel time confirmation
- travel documents
- arrival logistics
- accommodation options
- immigration appointment requirements

### Step 3: 生成 Itinerary

如果存在 `depart_at` 或 `return_at`，生成 `PlannedEvent`。

如需多日行程，调用 `/api/travel/itinerary`：

- 按日期生成 `TravelItineraryDay`。
- 生成 route buffer、住宿 check-in、主活动 block、返程 buffer。
- 根据 `budget_amount` 生成 transport / accommodation / food / local_transit / contingency 拆分。
- 如果已有 `weather.lookup` 返回的 forecast，写入天气提醒。

### Step 4: 天气工具

天气查询通过统一工具层执行：

- tool name：`weather.lookup`
- API：`/api/tools/run`
- permission level：`SEARCH`

天气结果只作为出行提醒，不作为订票、取消或安全结论的唯一依据。

### Step 5: 风险和审批

读取 [references/travel_boundaries.md](references/travel_boundaries.md)。

## 重要边界

- 不调用外部订票 MCP。
- 不执行支付。
- 不替用户确认签证、移民或法律结论。
- 不向第三方提交个人信息。
- 天气和路线信息需要出发前再次核验。
