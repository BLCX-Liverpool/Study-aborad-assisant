import { Mail, ShieldCheck } from "lucide-react";
import type { EmailDraft } from "../types";

type EmailDraftCardProps = {
  draft: EmailDraft;
};

export function EmailDraftCard({ draft }: EmailDraftCardProps) {
  return (
    <section className="panel email-panel">
      <div className="panel-heading">
        <Mail size={18} />
        <h2>Email Draft</h2>
      </div>
      <div className="email-meta">
        <span>{draft.recipient_type}</span>
        <span>{draft.tone}</span>
      </div>
      <h3>{draft.subject}</h3>
      <pre>{draft.body}</pre>
      {draft.missing_information.length ? (
        <div className="missing-box">
          <strong>Missing:</strong> {draft.missing_information.join(", ")}
        </div>
      ) : null}
      <div className="approval-note">
        <ShieldCheck size={16} />
        <span>{draft.requires_user_approval ? "User approval required before sending" : "Draft only"}</span>
      </div>
    </section>
  );
}

