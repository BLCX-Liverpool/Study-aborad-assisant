import { GitBranch } from "lucide-react";
import type { MultiIntentExecutionPlan } from "../types";

type ExecutionPlanPanelProps = {
  plan?: MultiIntentExecutionPlan | null;
};

export function ExecutionPlanPanel({ plan }: ExecutionPlanPanelProps) {
  return (
    <section className="panel review-panel">
      <div className="panel-heading">
        <GitBranch size={18} />
        <h2>Execution Plan</h2>
      </div>

      {!plan ? (
        <p className="module-hint">任务包含多个意图时，这里会展示执行顺序、依赖关系和每一步状态。</p>
      ) : null}

      {plan ? (
        <>
      <p className="objective">{plan.summary}</p>
      <div className="review-list">
        {plan.steps.map((step) => (
          <article className="mini-card" key={`${step.index}-${step.intent_name}`}>
            <div className="mini-card-header">
              <span>{step.intent_name}</span>
              <strong>{step.status}</strong>
            </div>
            {step.condition ? <p>{step.condition}</p> : null}
            {step.depends_on.length ? <p>Depends on: {step.depends_on.join(", ")}</p> : null}
            {step.result_summary ? <p>{step.result_summary}</p> : null}
          </article>
        ))}
      </div>

      {plan.email_reminder_drafts.length ? (
        <div className="compact-list">
          {plan.email_reminder_drafts.map((reminder) => (
            <div key={`${reminder.title}-${reminder.remind_at}`}>
              <strong>{reminder.title}</strong>
              <span>{new Date(reminder.remind_at).toLocaleString()}</span>
            </div>
          ))}
        </div>
      ) : null}
        </>
      ) : null}
    </section>
  );
}
