import { useEffect, useState } from "react";
import { CopyCheck, ShieldCheck } from "lucide-react";
import type { SocialContentOutput } from "../types";

type SocialContentPanelProps = {
  content?: SocialContentOutput | null;
};

export function SocialContentPanel({ content }: SocialContentPanelProps) {
  const [activeDraft, setActiveDraft] = useState(0);
  useEffect(() => setActiveDraft(0), [content]);
  const draft = content?.drafts[activeDraft] ?? content?.drafts[0];

  return (
    <section className="panel social-panel">
      <div className="panel-heading">
        <CopyCheck aria-hidden="true" size={18} />
        <h2>Social Content</h2>
      </div>

      {!content ? (
        <p className="module-hint">需要整理留学经验、申请记录或生活分享时，这里会生成平台适配的文案草稿。</p>
      ) : null}

      {content ? (
        <>
      <div className="email-meta">
        <span>{draft?.platform ?? "platform"}</span>
        <span>{draft?.variant ?? "variant"}</span>
        <span>{content.safety.level}</span>
      </div>

      {content.platform_standard ? (
        <div className="memory-note">{content.platform_standard.recommended_length}</div>
      ) : null}

      {content.fallback_used ? (
        <div className="social-fallback-note" role="status">
          当前使用本地确定性模板生成；模型服务恢复后可重新生成更自然的版本。
          {content.generation_error ? <small>{content.generation_error}</small> : null}
        </div>
      ) : null}

      {content.drafts.length > 1 ? (
        <div className="social-draft-tabs" role="tablist" aria-label="文案版本">
          {content.drafts.map((item, index) => (
            <button
              aria-selected={activeDraft === index}
              className={activeDraft === index ? "active" : ""}
              key={`${item.variant}-${index}`}
              onClick={() => setActiveDraft(index)}
              role="tab"
              type="button"
            >
              版本 {index + 1} · {item.variant}
            </button>
          ))}
        </div>
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
        <ShieldCheck aria-hidden="true" size={16} />
        <span>发布前请检查事实、隐私和平台规则。</span>
      </div>
        </>
      ) : null}
    </section>
  );
}
