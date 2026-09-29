import { AlarmClock, CalendarDays } from "lucide-react";
import type { PlannerOutput } from "../types";

type TaskTimelineProps = {
  plan: PlannerOutput;
};

export function TaskTimeline({ plan }: TaskTimelineProps) {
  return (
    <section className="panel timeline-panel">
      <div className="panel-heading">
        <CalendarDays size={18} />
        <h2>Task Timeline</h2>
      </div>
      {plan.selected_strategy && (
        <div className="planner-strategy-row">
          <span>{plan.selected_strategy.split("_").join(" ")}</span>
          <span>{plan.planning_candidates?.length ?? 0} candidates evaluated</span>
        </div>
      )}
      <ol className="timeline">
        {plan.tasks.map((task) => (
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
      <div className="reminder-row">
        <AlarmClock size={16} />
        <span>{plan.reminders.length} reminder draft prepared</span>
      </div>
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
