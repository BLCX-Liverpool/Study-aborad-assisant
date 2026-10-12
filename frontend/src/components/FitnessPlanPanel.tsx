import { Activity, Dumbbell, ShieldAlert } from "lucide-react";
import type { FitnessPlanOutput } from "../types";

type FitnessPlanPanelProps = {
  plan?: FitnessPlanOutput | null;
};

export function FitnessPlanPanel({ plan }: FitnessPlanPanelProps) {
  return (
    <section className="panel fitness-panel">
      <div className="panel-heading">
        <Dumbbell size={18} />
        <h2>Fitness Plan</h2>
      </div>

      {!plan ? (
        <p className="module-hint">提出健身、作息或压力管理目标后，这里会生成训练日安排、习惯任务和安全提示。</p>
      ) : null}

      {plan ? (
        <>
      <p className="objective">{plan.summary}</p>

      <div className="workout-grid">
        {plan.workout_days.map((day) => (
          <article className="mini-card" key={`${day.day_of_week}-${day.focus}`}>
            <div className="mini-card-header">
              <span>{day.day_of_week}</span>
              <strong>{day.duration_minutes} min</strong>
            </div>
            <h3>{day.focus}</h3>
            <ul>
              {day.blocks.slice(0, 3).map((block) => (
                <li key={block.name}>
                  {block.name}: {block.duration_minutes} min
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>

      <div className="reminder-row">
        <Activity size={16} />
        <span>
          {plan.habit_tasks.length} habit task and {plan.schedule_tasks.length} schedule task prepared
        </span>
      </div>

      {plan.progression.length ? (
        <div className="compact-list">
          {plan.progression.slice(0, 2).map((week) => (
            <div key={week.week}>
              <strong>Week {week.week}</strong>
              <span>{week.progression_rule}</span>
            </div>
          ))}
        </div>
      ) : null}

      {plan.memory_candidates.length ? (
        <div className="memory-note">
          {plan.memory_candidates[0].requires_confirmation
            ? "Fitness preferences are prepared as confirmation-required memory candidates."
            : "Fitness preferences can be stored as memory."}
        </div>
      ) : null}

      {plan.risk_notes.length ? (
        <div className="warning-strip">
          <ShieldAlert size={16} />
          <span>{plan.risk_notes[0]}</span>
        </div>
      ) : null}
        </>
      ) : null}
    </section>
  );
}
