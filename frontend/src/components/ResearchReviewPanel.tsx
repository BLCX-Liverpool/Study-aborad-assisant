import { Loader2, Microscope } from "lucide-react";
import { useMemo, useState } from "react";
import type {
  ArxivSourceCandidates,
  IdeaVerificationResponse,
  ResearchSource,
  SelectedResearchSourceIndexResponse
} from "../types";

type ResearchReviewPanelProps = {
  sources: ResearchSource[];
  verification?: IdeaVerificationResponse | null;
  arxivCandidates?: ArxivSourceCandidates | null;
  indexingResult?: SelectedResearchSourceIndexResponse | null;
  indexingLoading?: boolean;
  indexingError?: string | null;
  onIndexSelected?: (sources: ResearchSource[]) => void;
};

export function ResearchReviewPanel({
  sources,
  verification,
  arxivCandidates,
  indexingResult,
  indexingLoading = false,
  indexingError,
  onIndexSelected
}: ResearchReviewPanelProps) {
  const firstFinding = verification?.findings[0];
  const candidates = arxivCandidates?.sources ?? [];
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set());
  const selectedSources = useMemo(
    () => candidates.filter((source) => selectedUrls.has(source.url)),
    [candidates, selectedUrls]
  );

  function toggleSource(source: ResearchSource) {
    setSelectedUrls((current) => {
      const next = new Set(current);
      if (next.has(source.url)) {
        next.delete(source.url);
      } else {
        next.add(source.url);
      }
      return next;
    });
  }

  return (
    <section className="panel review-panel">
      <div className="panel-heading">
        <Microscope size={18} />
        <h2>Research Review</h2>
      </div>

      {!sources.length && !firstFinding && !candidates.length ? (
        <p className="module-hint">当任务涉及选题、论文或资料检索时，这里会展示研究来源、候选文献和选题验证结果。</p>
      ) : null}

      {sources.length || verification?.recommended_ideas.length ? (
        <div className="email-meta">
          <span>{sources.length} sources</span>
          <span>{verification?.recommended_ideas.length ?? 0} recommended</span>
        </div>
      ) : null}

      {candidates.length ? (
        <div className="research-candidates">
          <div className="mini-card-header">
            <span>{arxivCandidates?.status}</span>
            <strong>ArXiv candidates</strong>
          </div>
          <div className="source-list selectable-source-list">
            {candidates.slice(0, 8).map((source) => (
              <article key={source.url}>
                <label className="source-choice">
                  <input
                    type="checkbox"
                    checked={selectedUrls.has(source.url)}
                    onChange={() => toggleSource(source)}
                  />
                  <span>
                    <strong>{source.title}</strong>
                    <small>{source.authors.slice(0, 3).join(", ") || "Unknown authors"}</small>
                  </span>
                </label>
                {source.summary ? <p>{source.summary}</p> : null}
              </article>
            ))}
          </div>
          <button
            className="secondary-button"
            type="button"
            disabled={!selectedSources.length || indexingLoading || !onIndexSelected}
            onClick={() => onIndexSelected?.(selectedSources)}
          >
            {indexingLoading ? <Loader2 className="spin" size={16} /> : <Microscope size={16} />}
            Index selected papers
          </button>
          {indexingError ? <p className="error-text">{indexingError}</p> : null}
          {indexingResult ? (
            <p className="memory-action-note">
              Indexed {indexingResult.indexed_file_ids.length} paper(s): {indexingResult.indexed_file_ids.join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}

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
