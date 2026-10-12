import { CheckCircle2, Circle, Loader2, OctagonAlert } from "lucide-react";
import type { TraceStep } from "../types";

type AgentTracePanelProps = {
  trace: TraceStep[];
};

const icons = {
  idle: Circle,
  running: Loader2,
  done: CheckCircle2,
  blocked: OctagonAlert
};

export function AgentTracePanel({ trace }: AgentTracePanelProps) {
  return (
    <section className="panel trace-panel">
      <div className="panel-heading">
        <CheckCircle2 size={18} />
        <h2>Agent Trace</h2>
      </div>
      {trace.length ? (
        <ol className="trace-list">
          {trace.map((step) => {
          const Icon = icons[step.status];
          return (
            <li key={step.name}>
              <Icon className={step.status === "running" ? "spin" : ""} size={16} />
              <div>
                <strong>{step.name}</strong>
                <span>{step.detail}</span>
              </div>
            </li>
          );
          })}
        </ol>
      ) : (
        <p className="module-hint">运行任务后，这里会显示路由器和各个智能体的执行步骤。</p>
      )}
    </section>
  );
}
