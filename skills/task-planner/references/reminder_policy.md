# Reminder Policy

## 默认提醒

任务 deadline 存在时：

- deadline 前 24 小时提醒。
- urgent/high priority 可增加 deadline 前 2 小时提醒。

事件 start_time 存在时：

- start_time 前 60 分钟提醒。

## 不创建提醒的情况

- 没有明确时间。
- 用户明确表示不需要提醒。
- 该任务只是泛化建议，没有可执行截止时间。

## 冲突处理

发现冲突时应返回冲突说明，不自动删除或覆盖已有事件。
