import { BookOpen, CheckCircle2, CircleAlert, FileSearch } from "lucide-react";
import type { AssignmentAnalysis } from "../types";

type AssignmentSummaryProps = {
  assignment: AssignmentAnalysis;
};

export function AssignmentSummary({ assignment }: AssignmentSummaryProps) {
  const evidenceCount = [
    ...assignment.marking_criteria,
    ...assignment.constraints
  ].reduce((count, requirement) => count + requirement.evidence.length, 0);

  return (
    <section className="panel assignment-panel">
      <div className="panel-heading">
        <BookOpen size={18} />
        <h2>Assignment Analysis</h2>
      </div>
      <div className="assignment-header">
        <div>
          <p className="eyebrow">{assignment.course_code ?? "Course"}</p>
          <h3>{assignment.title ?? "Untitled assignment"}</h3>
        </div>
        <span className="deadline-pill">{formatDate(assignment.deadline)}</span>
      </div>
      <p className="objective">{assignment.objective}</p>

      <div className="summary-columns">
        <div>
          <h4>
            <CheckCircle2 size={15} />
            Deliverables
          </h4>
          <ul>
            {assignment.deliverables.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>
            <FileSearch size={15} />
            Evidence
          </h4>
          <p className="metric">{evidenceCount}</p>
          <span className="muted">source-backed facts</span>
        </div>
      </div>

      {assignment.missing_information.length ? (
        <div className="warning-strip">
          <CircleAlert size={16} />
          <span>{assignment.missing_information.join(" ")}</span>
        </div>
      ) : null}
    </section>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "No deadline";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

