import { CopyCheck, ShieldCheck } from "lucide-react";
import type { SocialContentOutput } from "../types";

type SocialContentPanelProps = {
  content: SocialContentOutput;
};

export function SocialContentPanel({ content }: SocialContentPanelProps) {
  const draft = content.drafts[0];

  return (
    <section className="panel social-panel">
      <div className="panel-heading">
        <CopyCheck size={18} />
        <h2>Social Content</h2>
      </div>

      <div className="email-meta">
        <span>{draft?.platform ?? "platform"}</span>
        <span>{draft?.variant ?? "variant"}</span>
        <span>{content.safety.level}</span>
      </div>

      {content.platform_standard ? (
        <div className="memory-note">{content.platform_standard.recommended_length}</div>
      ) : null}

      {draft ? (
        <>
          {draft.title ? <h3>{draft.title}</h3> : null}
          <pre>{draft.body}</pre>
          {draft.platform_fit_notes.length ? (
            <ul className="compact-points">
              {draft.platform_fit_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : null}
          <div className="hashtag-row">
            {draft.hashtags.map((tag) => (
              <span key={tag}>#{tag}</span>
            ))}
          </div>
        </>
      ) : (
        <p className="muted">No draft generated because the request needs review.</p>
      )}

      <div className="approval-note">
        <ShieldCheck size={16} />
        <span>{content.image_generation_tool?.boundary ?? content.disclaimer}</span>
      </div>
    </section>
  );
}
