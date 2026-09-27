# Evidence Rules

## 必须绑定 Evidence 的字段

- deadline
- deliverables
- marking criteria
- word limit
- submission format
- required citation style
- required data/source constraint

## Evidence 质量

高质量 evidence 应满足：

1. 原文 quote 能直接支持结论。
2. 页码或章节可追溯。
3. confidence 不低于 `0.7`。

## 低置信度处理

如果 evidence 冲突或置信度不足：

- 保留最保守的解释。
- 在 `missing_information` 中提示用户确认。
- 不自动生成确定 deadline 或提交要求。
