import { Check, Loader2, RefreshCcw, Trash2, X } from "lucide-react";
import type { MemoryDecisionResponse, MemoryReviewResponse } from "../types";

type MemoryReviewPanelProps = {
  review?: MemoryReviewResponse | null;
  loading?: boolean;
  error?: string | null;
  lastAction?: MemoryDecisionResponse | null;
  onRefresh: () => void;
  onConfirm: (memoryId: string) => void;
  onReject: (memoryId: string) => void;
  onDelete: (memoryId: string) => void;
};

export function MemoryReviewPanel({
  review,
  loading = false,
  error,
  lastAction,
  onRefresh,
  onConfirm,
  onReject,
  onDelete
}: MemoryReviewPanelProps) {
  const candidates = review?.candidates ?? [];
  const memories = review?.memories ?? [];

  return (
    <div className="panel memory-review-panel">
      <div className="panel-heading action-heading">
        <RefreshCcw size={18} />
        <h2>Memory Review</h2>
        <button className="icon-button" type="button" onClick={onRefresh} disabled={loading} aria-label="Refresh memory review">
          {loading ? <Loader2 className="spin" size={16} /> : <RefreshCcw size={16} />}
        </button>
      </div>

      {error ? <p className="error-text">{error}</p> : null}
      {lastAction ? <p className="memory-action-note">{lastAction.status}: {lastAction.memory_ids.length} item(s)</p> : null}
      {!review ? (
        <p className="module-hint">运行任务或点击刷新后，这里会列出待确认记忆和已保存的偏好。</p>
      ) : null}

      {review ? (
        <>
          <div className="memory-section">
            <h3>Pending</h3>
            {candidates.length ? (
              <ul className="memory-list">
                {candidates.slice(0, 6).map((item) => (
                  <li key={item.id ?? item.content}>
                    <div>
                      <strong>{item.namespace}</strong>
                      <p>{item.content}</p>
                    </div>
                    {item.id ? (
                      <div className="memory-actions">
                        <button type="button" className="icon-button" onClick={() => onConfirm(item.id!)} aria-label="Confirm memory">
                          <Check size={15} />
                        </button>
                        <button type="button" className="icon-button" onClick={() => onReject(item.id!)} aria-label="Reject memory">
                          <X size={15} />
                        </button>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No pending memory candidates.</p>
            )}
          </div>

          <div className="memory-section">
            <h3>Stored</h3>
            {memories.length ? (
              <ul className="memory-list">
                {memories.slice(0, 6).map((item) => (
                  <li key={item.id ?? item.content}>
                    <div>
                      <strong>{item.namespace}</strong>
                      <p>{item.content}</p>
                    </div>
                    {item.id ? (
                      <button type="button" className="icon-button" onClick={() => onDelete(item.id!)} aria-label="Delete memory">
                        <Trash2 size={15} />
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No confirmed memories.</p>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
