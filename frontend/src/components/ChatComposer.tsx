import { CornerDownLeft, Loader2 } from "lucide-react";
import type { ChatApiResponse } from "../types";

type ChatComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onRun: () => void;
  loading?: boolean;
  response?: ChatApiResponse | null;
  error?: string | null;
};

export function ChatComposer({ value, onChange, onRun, loading = false, response, error }: ChatComposerProps) {
  const memoryContext = response?.memory_context as
    | {
        routing?: { namespaces?: string[]; memory_source?: string[] };
        topic?: { relation?: string };
      }
    | undefined;

  return (
    <div className="chat-composer">
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label="Message"
      />
      <button className="primary-button" type="button" onClick={onRun} disabled={loading}>
        {loading ? <Loader2 className="spin" size={16} /> : <CornerDownLeft size={16} />}
        Run locally
      </button>
      {error ? <p className="error-text">{error}</p> : null}
      {response ? (
        <div className="chat-response">
          <strong>Response</strong>
          <p>{response.final_response}</p>
          <div className="memory-context-chip">
            <span>{memoryContext?.topic?.relation ?? "memory"}</span>
            <span>{memoryContext?.routing?.namespaces?.join(", ") ?? "shared"}</span>
          </div>
          {response.missing_information.length ? (
            <div className="missing-box">{response.missing_information.join(", ")}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
