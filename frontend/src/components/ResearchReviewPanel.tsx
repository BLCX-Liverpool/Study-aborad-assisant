import { Microscope } from "lucide-react";
import type { IdeaVerificationResponse, ResearchSource } from "../types";

type ResearchReviewPanelProps = {
  sources: ResearchSource[];
  verification: IdeaVerificationResponse;
};

export function ResearchReviewPanel({ sources, verification }: ResearchReviewPanelProps) {
  const firstFinding = verification.findings[0];

  return (
    <section className="panel review-panel">
      <div className="panel-heading">
        <Microscope size={18} />
        <h2>Research Review</h2>
      </div>

      <div className="email-meta">
        <span>{sources.length} sources</span>
        <span>{verification.recommended_ideas.length} recommended</span>
      </div>

      {firstFinding ? (
        <article className="mini-card">
          <div className="mini-card-header">
            <span>{firstFinding.status}</span>
            <strong>idea</strong>
          </div>
          <h3>{firstFinding.idea}</h3>
          <ul>
            {firstFinding.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </article>
      ) : null}

      <div className="source-list">
        {sources.slice(0, 3).map((source) => (
          <article key={source.url}>
            <strong>{source.title}</strong>
            <span>{source.source_type}</span>
            {source.summary ? <p>{source.summary}</p> : null}
          </article>
        ))}
      </div>
    </section>
  );
}
