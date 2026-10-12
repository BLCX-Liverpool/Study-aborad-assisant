import { AlarmClock, CalendarDays } from "lucide-react";
import type { PlannerOutput } from "../types";

type TaskTimelineProps = {
  plan?: PlannerOutput | null;
};

export function TaskTimeline({ plan }: TaskTimelineProps) {
  const tasks = plan?.tasks ?? [];

  return (
    <section className="panel timeline-panel">
      <div className="panel-heading">
        <CalendarDays size={18} />
        <h2>Task Timeline</h2>
      </div>
      {!plan ? (
        <p className="module-hint">输入任务并运行后，这里会把学习、申请或生活事项拆成时间线和提醒草稿。</p>
      ) : null}
      {plan?.selected_strategy && (
        <div className="planner-strategy-row">
          <span>{plan.selected_strategy.split("_").join(" ")}</span>
          <span>{plan.planning_candidates?.length ?? 0} candidates evaluated</span>
        </div>
      )}
      {tasks.length ? (
        <ol className="timeline">
          {tasks.map((task) => (
          <li key={task.title}>
            <div className={`priority-dot ${task.priority}`} />
            <div className="timeline-content">
              <div className="timeline-title-row">
                <h3>{task.title}</h3>
                <span>{task.priority}</span>
              </div>
              <p>{task.description}</p>
              <time>{formatRange(task.start_time, task.deadline)}</time>
            </div>
          </li>
          ))}
        </ol>
      ) : null}
      {plan ? (
        <div className="reminder-row">
          <AlarmClock size={16} />
          <span>{plan.reminders.length} reminder draft prepared</span>
        </div>
      ) : null}
    </section>
  );
}

function formatRange(start?: string | null, end?: string | null) {
  const formatter = new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
  if (start && end) return `${formatter.format(new Date(start))} -> ${formatter.format(new Date(end))}`;
  if (end) return `Due ${formatter.format(new Date(end))}`;
  return "Unscheduled";
}
