# 留学生活助手 Benchmark v1.0

冻结日期：2026-11-24

数据由 `backend/tests/benchmark_dataset_generator.py` 确定性生成。修改样本定义后，在仓库根目录运行 `./.venv/bin/python backend/tests/benchmark_dataset_generator.py` 重新生成；不要只手工修改生成后的表格。

## 正式评估集

| 评估维度 | 文件 | 规模 |
| --- | --- | ---: |
| 任务完成率 | [task_success_500.md](task_success_500.md) | 500 |
| 意图识别 | [intent_recognition_500.md](intent_recognition_500.md) | 500 |
| 工具调用 | [tool_calling_500.md](tool_calling_500.md) | 500 |
| 系统性能 | [performance_scenarios.md](performance_scenarios.md) | 12组 |

## 任务成功率

唯一主公式：

`Task Success Rate = 成功完成的测试任务数 / 全部测试任务数`

“硬规则 + Rubric + 抽样人工复核”用于决定单条任务是否成功，不产生另一套成功率公式：

1. 全部硬规则通过；
2. Rubric达到4/5；
3. 被抽中的样本经人工复核确认；
4. 满足以上条件记为1，否则记为0。

## 冻结与复现

- 评估报告必须记录Git commit、LLM/Embedding模型、Prompt版本、环境变量能力开关和运行日期。
- 固定文件、Tool和Provider结果应使用版本化Fixture；真实外部依赖结果单独报告。
- 不得在查看正式评估结果后直接修改同版本标签；修订需发布v1.1或v2.0。
- 随机生成类响应至少运行3次，任务成功按预先声明的聚合规则统计。
- 安全、审批、幂等和重复副作用为硬门槛，不允许被平均质量分抵消。

## Fixture约定

- `fixtures/assignments/brief_01.pdf` 至 `brief_10.pdf`：固定课程作业说明，需包含可验证的deadline、deliverable、rubric和constraint。
- Tool正向样本使用固定Mock响应；不可用样本返回`available=false`或`recoverable_error`。
- 性能集中的大文件夹具固定为20页PDF，并记录文件哈希。

## 报告最小字段

每次运行至少输出：case_id、pass/fail、实际Router、实际Agent/Step、实际Tool调用、Artifact、终态、各阶段耗时、失败原因、人工复核结论。
