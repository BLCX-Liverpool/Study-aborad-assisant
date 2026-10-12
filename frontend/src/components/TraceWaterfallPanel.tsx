import { Activity, Search } from "lucide-react";
import type { TraceWaterfallResponse } from "../types";

type TraceWaterfallPanelProps = {
  traceId: string;
  onTraceIdChange: (value: string) => void;
  onLookup: () => void;
  loading: boolean;
  error?: string | null;
  waterfall?: TraceWaterfallResponse | null;
};

export function TraceWaterfallPanel({
  traceId,
  onTraceIdChange,
  onLookup,
  loading,
  error,
  waterfall
}: TraceWaterfallPanelProps) {
  const total = waterfall?.summary?.total_duration_ms ?? 0;

  return (
    <section className="panel trace-waterfall-panel">
      <div className="panel-heading">
        <Activity size={18} />
        <h2>Trace Waterfall</h2>
      </div>

      <div className="trace-query-row">
        <input
          aria-label="Trace ID"
          value={traceId}
          onChange={(event) => onTraceIdChange(event.target.value)}
          placeholder="trace_id"
        />
        <button className="secondary-button" type="button" onClick={onLookup} disabled={loading || !traceId.trim()}>
          <Search size={16} />
          {loading ? "Loading..." : "Lookup"}
        </button>
      </div>

      {error ? <p className="error-text">{error}</p> : null}
      {!traceId.trim() && !waterfall ? (
        <p className="module-hint">运行任务后会自动填入 trace id；也可以手动输入 trace id 查看调用耗时瀑布图。</p>
      ) : null}

      {waterfall?.found && waterfall.summary ? (
        <>
          <div className="trace-summary-grid">
            <div>
              <span>Total</span>
              <strong>{Math.round(waterfall.summary.total_duration_ms)} ms</strong>
            </div>
            <div>
              <span>Spans</span>
              <strong>{waterfall.summary.span_count}</strong>
            </div>
            <div>
              <span>Failed</span>
              <strong>{waterfall.summary.failed_span_count}</strong>
            </div>
          </div>

          <ol className="waterfall-list">
            {waterfall.spans.map((span) => {
              const width = total > 0 ? Math.max((span.duration_ms / total) * 100, 3) : 3;
              const offset = total > 0 ? Math.min((span.offset_ms / total) * 100, 96) : 0;
              return (
                <li key={span.span_id}>
                  <div className="waterfall-row-header" style={{ paddingLeft: span.depth * 14 }}>
                    <strong>{span.span_name}</strong>
                    <span>{Math.round(span.duration_ms)} ms</span>
                  </div>
                  <div className="waterfall-track" aria-label={`${span.span_name} duration`}>
                    <div
                      className={`waterfall-bar ${span.status === "failed" ? "failed" : ""}`}
                      style={{ marginLeft: `${offset}%`, width: `${width}%` }}
                    />
                  </div>
                  <div className="waterfall-meta">
                    <span>{span.span_type}</span>
                    <span>{span.status}</span>
                  </div>
                </li>
              );
            })}
          </ol>
        </>
      ) : null}

      {waterfall && !waterfall.found ? <p className="muted">No spans found for this trace.</p> : null}
    </section>
  );
}
