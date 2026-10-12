import { ClipboardCheck } from "lucide-react";
import type { ActionItem } from "../types";

type NoticeActionReviewPanelProps = {
  actions: ActionItem[];
};

export function NoticeActionReviewPanel({ actions }: NoticeActionReviewPanelProps) {
  return (
    <section className="panel review-panel">
      <div className="panel-heading">
        <ClipboardCheck size={18} />
        <h2>Notice Review</h2>
      </div>

      {actions.length ? (
        <div className="review-list">
          {actions.map((action) => (
          <article className="mini-card" key={`${action.action_type}-${action.title}`}>
            <div className="mini-card-header">
              <span>{action.action_type}</span>
              <strong>{action.priority}</strong>
            </div>
            <h3>{action.title}</h3>
            {action.description ? <p>{action.description}</p> : null}
            {action.deadline ? <time>{new Date(action.deadline).toLocaleString()}</time> : null}
            {action.evidence[0]?.quote ? (
              <blockquote>{action.evidence[0].quote}</blockquote>
            ) : null}
          </article>
          ))}
        </div>
      ) : (
        <p className="module-hint">运行任务后，这里会提取通知、邮件或文件中的 deadline、待办事项和需要审批的动作。</p>
      )}
    </section>
  );
}
