import { useMemo, useState } from "react";
import {
  Bot,
  Bug,
  ChevronRight,
  FileText,
  Loader2,
  MessageSquareText,
  PanelRightClose,
  Send,
  Sparkles,
  SquarePen,
  UserRound
} from "lucide-react";
import { AssignmentSummary } from "./components/AssignmentSummary";
import { TaskTimeline } from "./components/TaskTimeline";
import { EmailDraftCard } from "./components/EmailDraftCard";
import { ExecutionPlanPanel } from "./components/ExecutionPlanPanel";
import { AgentTracePanel } from "./components/AgentTracePanel";
import { FileUploader } from "./components/FileUploader";
import { FitnessPlanPanel } from "./components/FitnessPlanPanel";
import { MemoryReviewPanel } from "./components/MemoryReviewPanel";
import { NoticeActionReviewPanel } from "./components/NoticeActionReviewPanel";
import { ResearchReviewPanel } from "./components/ResearchReviewPanel";
import { SocialContentPanel } from "./components/SocialContentPanel";
import { TraceWaterfallPanel } from "./components/TraceWaterfallPanel";
import {
  confirmMemoryCandidates,
  deleteMemories,
  fetchMemoryReview,
  fetchTraceWaterfall,
  indexSelectedArxivSources,
  rejectMemoryCandidates,
  sendChatMessage
} from "./lib/api";
import type {
  ActionItem,
  AssignmentAnalysis,
  ChatApiResponse,
  EmailDraft,
  FitnessPlanOutput,
  MemoryDecisionResponse,
  MemoryReviewResponse,
  MultiIntentExecutionPlan,
  PlannerOutput,
  ArxivSourceCandidates,
  ResearchSource,
  SelectedResearchSourceIndexResponse,
  SocialContentOutput,
  TraceStep,
  TraceWaterfallResponse,
  UploadedFile
} from "./types";

const userId = "local_user";

type ConversationMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  response?: ChatApiResponse;
  uploadedFile?: UploadedFile | null;
};

type ConversationSession = {
  id: string;
  title: string;
  activeMessage: string;
  uploadedFile: UploadedFile | null;
  messages: ConversationMessage[];
  chatResponse: ChatApiResponse | null;
  traceQuery: string;
  traceWaterfall: TraceWaterfallResponse | null;
  researchIndexingResult: SelectedResearchSourceIndexResponse | null;
};

const initialConversation = createConversationSession(1);

export function App() {
  const [sessions, setSessions] = useState<ConversationSession[]>([initialConversation]);
  const [activeConversationId, setActiveConversationId] = useState(initialConversation.id);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [memoryReview, setMemoryReview] = useState<MemoryReviewResponse | null>(null);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoryAction, setMemoryAction] = useState<MemoryDecisionResponse | null>(null);
  const [researchIndexingLoading, setResearchIndexingLoading] = useState(false);
  const [researchIndexingError, setResearchIndexingError] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const activeSession = sessions.find((session) => session.id === activeConversationId) ?? sessions[0];
  const activeMessage = activeSession.activeMessage;
  const chatResponse = activeSession.chatResponse;
  const traceQuery = activeSession.traceQuery;
  const traceWaterfall = activeSession.traceWaterfall;
  const researchIndexingResult = activeSession.researchIndexingResult;
  const latestAssistantResponse = latestResponse(activeSession);
  const detailResponse = latestAssistantResponse ?? chatResponse;
  const detailTrace = traceFromResponse(detailResponse);

  const detailSummary = useMemo(() => {
    if (!detailResponse) {
      return { agents: 0, artifacts: 0, trace: "Waiting" };
    }
    return {
      agents: detailResponse.trace.length,
      artifacts: detailResponse.artifacts.length,
      trace: detailResponse.trace_id || "No trace"
    };
  }, [detailResponse]);

  function updateSession(sessionId: string, patch: Partial<ConversationSession>) {
    setSessions((current) =>
      current.map((session) => (session.id === sessionId ? { ...session, ...patch } : session))
    );
  }

  function patchSession(sessionId: string, updater: (session: ConversationSession) => ConversationSession) {
    setSessions((current) => current.map((session) => (session.id === sessionId ? updater(session) : session)));
  }

  function updateActiveSession(patch: Partial<ConversationSession>) {
    updateSession(activeSession.id, patch);
  }

  function startNewConversation() {
    const session = createConversationSession(sessions.length + 1);
    setSessions((current) => [session, ...current]);
    setActiveConversationId(session.id);
    setChatError(null);
    setTraceError(null);
    setResearchIndexingError(null);
  }

  async function runChat() {
    const session = activeSession;
    const message = session.activeMessage.trim();
    if (!message || chatLoading) {
      return;
    }

    const userMessage: ConversationMessage = {
      id: createMessageId("user"),
      role: "user",
      content: message,
      createdAt: new Date().toISOString(),
      uploadedFile: session.uploadedFile
    };

    patchSession(session.id, (current) => ({
      ...current,
      activeMessage: "",
      messages: [...current.messages, userMessage]
    }));
    setChatLoading(true);
    setChatError(null);

    try {
      const response = await sendChatMessage({
        userId,
        message,
        conversationId: session.id,
        agentInputs: session.uploadedFile
          ? {
              assignment: {
                file_id: session.uploadedFile.file_id,
                source_path: session.uploadedFile.storage_path,
                source_name: session.uploadedFile.filename,
                mime_type: session.uploadedFile.mime_type
              }
            }
          : {}
      });

      const assistantMessage: ConversationMessage = {
        id: createMessageId("assistant"),
        role: "assistant",
        content: response.final_response,
        createdAt: new Date().toISOString(),
        response
      };

      patchSession(session.id, (current) => ({
        ...current,
        chatResponse: response,
        messages: [...current.messages, assistantMessage],
        title: deriveSessionTitle(current, response.final_response, message),
        traceQuery: response.trace_id,
        traceWaterfall: null,
        researchIndexingResult: null
      }));
      await loadTraceWaterfall(response.trace_id, session.id);
      await loadMemoryReview();
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "Chat request failed");
      patchSession(session.id, (current) => ({
        ...current,
        activeMessage: message
      }));
    } finally {
      setChatLoading(false);
    }
  }

  async function loadTraceWaterfall(traceId = traceQuery, sessionId = activeSession.id) {
    const normalized = traceId.trim();
    if (!normalized) {
      return;
    }
    setTraceLoading(true);
    setTraceError(null);
    try {
      const waterfall = await fetchTraceWaterfall(normalized);
      patchSession(sessionId, (current) => ({ ...current, traceWaterfall: waterfall, traceQuery: normalized }));
    } catch (error) {
      setTraceError(error instanceof Error ? error.message : "Trace lookup failed");
    } finally {
      setTraceLoading(false);
    }
  }

  async function loadMemoryReview() {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      const review = await fetchMemoryReview(userId);
      setMemoryReview(review);
    } catch (error) {
      setMemoryError(error instanceof Error ? error.message : "Memory review failed");
    } finally {
      setMemoryLoading(false);
    }
  }

  async function runMemoryAction(action: (user: string, ids: string[]) => Promise<MemoryDecisionResponse>, memoryId: string) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      const result = await action(userId, [memoryId]);
      setMemoryAction(result);
      await loadMemoryReview();
    } catch (error) {
      setMemoryError(error instanceof Error ? error.message : "Memory action failed");
    } finally {
      setMemoryLoading(false);
    }
  }

  async function runIndexSelectedArxivSources(sources: ResearchSource[]) {
    const session = activeSession;
    setResearchIndexingLoading(true);
    setResearchIndexingError(null);
    try {
      const result = await indexSelectedArxivSources({
        userId,
        sources,
        conversationId: session.id,
        traceId: session.chatResponse?.trace_id
      });
      patchSession(session.id, (current) => ({ ...current, researchIndexingResult: result }));
    } catch (error) {
      setResearchIndexingError(error instanceof Error ? error.message : "ArXiv indexing failed");
    } finally {
      setResearchIndexingLoading(false);
    }
  }

  return (
    <main className="chat-app-shell">
      <aside className="chat-sidebar" aria-label="Conversations">
        <div className="sidebar-brand">
          <div className="brand-mark">
            <Sparkles size={18} />
          </div>
          <div>
            <p>Study Abroad</p>
            <strong>Life Assistant</strong>
          </div>
        </div>

        <button className="new-chat-button" type="button" onClick={startNewConversation}>
          <SquarePen size={16} />
          New chat
        </button>

        <div className="sidebar-section-label">Conversations</div>
        <div className="chat-session-list">
          {sessions.map((session) => (
            <button
              className={session.id === activeSession.id ? "chat-session-item active" : "chat-session-item"}
              key={session.id}
              type="button"
              onClick={() => {
                setActiveConversationId(session.id);
                setChatError(null);
                setTraceError(null);
                setResearchIndexingError(null);
              }}
            >
              <MessageSquareText size={15} />
              <span>{session.title}</span>
            </button>
          ))}
        </div>

        <div className="sidebar-footer">
          <button className="detail-entry-button" type="button" onClick={() => setDetailOpen(true)}>
            <Bug size={15} />
            <span>Detail</span>
            <ChevronRight size={14} />
          </button>
          <div className="detail-meta">
            <span>{detailSummary.agents} calls</span>
            <span>{detailSummary.artifacts} artifacts</span>
          </div>
        </div>
      </aside>

      <section className="chat-main" aria-label="Chat workspace">
        <header className="chat-main-header">
          <div>
            <p className="eyebrow">Unified assistant</p>
            <h1>{activeSession.title}</h1>
          </div>
          <button className="subtle-button" type="button" onClick={() => setDetailOpen(true)}>
            <Bug size={15} />
            Detail
          </button>
        </header>

        <section className="message-scroll" aria-label="Messages">
          {activeSession.messages.length ? (
            activeSession.messages.map((message) => (
              <ChatMessageBubble
                key={message.id}
                message={message}
                indexingResult={researchIndexingResult}
                indexingLoading={researchIndexingLoading}
                indexingError={researchIndexingError}
                onIndexSelected={runIndexSelectedArxivSources}
              />
            ))
          ) : (
            <div className="empty-chat-state">
              <div className="empty-chat-icon">
                <Bot size={28} />
              </div>
              <h2>What can I help you handle today?</h2>
              <p>Ask about coursework, applications, email drafting, budgeting, travel, wellbeing, or fitness. Results will appear here as one conversation.</p>
            </div>
          )}
          {chatLoading ? (
            <div className="message-row assistant">
              <div className="message-avatar">
                <Bot size={17} />
              </div>
              <div className="message-bubble loading-bubble">
                <Loader2 className="spin" size={16} />
                <span>Analyzing and routing your task...</span>
              </div>
            </div>
          ) : null}
        </section>

        <section className="composer-shell" aria-label="Message composer">
          {activeSession.uploadedFile ? (
            <div className="composer-file-chip">
              <FileText size={14} />
              <span>{activeSession.uploadedFile.filename}</span>
            </div>
          ) : null}
          {chatError ? <p className="error-text">{chatError}</p> : null}
          <div className="composer-box">
            <textarea
              aria-label="Message"
              value={activeMessage}
              onChange={(event) => updateActiveSession({ activeMessage: event.target.value })}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  void runChat();
                }
              }}
              placeholder="Message Study Abroad Assistant..."
            />
            <div className="composer-actions">
              <FileUploader
                userId={userId}
                conversationId={activeSession.id}
                onUploaded={(file) => updateActiveSession({ uploadedFile: file })}
              />
              <button className="send-button" type="button" onClick={() => void runChat()} disabled={chatLoading || !activeMessage.trim()}>
                {chatLoading ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
              </button>
            </div>
          </div>
        </section>
      </section>

      {detailOpen ? (
        <aside className="detail-drawer" aria-label="Detail">
          <div className="detail-drawer-header">
            <div>
              <p className="eyebrow">Developer detail</p>
              <h2>Detail</h2>
            </div>
            <button className="icon-button" type="button" onClick={() => setDetailOpen(false)} aria-label="Close detail">
              <PanelRightClose size={17} />
            </button>
          </div>

          <div className="detail-summary-grid">
            <div>
              <span>Agent calls</span>
              <strong>{detailSummary.agents}</strong>
            </div>
            <div>
              <span>Artifacts</span>
              <strong>{detailSummary.artifacts}</strong>
            </div>
          </div>
          <p className="detail-trace-id">{detailSummary.trace}</p>

          <AgentTracePanel trace={detailTrace} />
          <TraceWaterfallPanel
            traceId={traceQuery || detailResponse?.trace_id || ""}
            onTraceIdChange={(value) => updateActiveSession({ traceQuery: value })}
            onLookup={() => void loadTraceWaterfall()}
            loading={traceLoading}
            error={traceError}
            waterfall={traceWaterfall}
          />
          <MemoryReviewPanel
            review={memoryReview}
            loading={memoryLoading}
            error={memoryError}
            lastAction={memoryAction}
            onRefresh={loadMemoryReview}
            onConfirm={(memoryId) => runMemoryAction(confirmMemoryCandidates, memoryId)}
            onReject={(memoryId) => runMemoryAction(rejectMemoryCandidates, memoryId)}
            onDelete={(memoryId) => runMemoryAction(deleteMemories, memoryId)}
          />
          <ArtifactDetail response={detailResponse} />
        </aside>
      ) : null}
    </main>
  );
}

function ChatMessageBubble({
  message,
  indexingResult,
  indexingLoading,
  indexingError,
  onIndexSelected
}: {
  message: ConversationMessage;
  indexingResult: SelectedResearchSourceIndexResponse | null;
  indexingLoading: boolean;
  indexingError: string | null;
  onIndexSelected: (sources: ResearchSource[]) => void;
}) {
  const isAssistant = message.role === "assistant";

  return (
    <article className={isAssistant ? "message-row assistant" : "message-row user"}>
      <div className="message-avatar">
        {isAssistant ? <Bot size={17} /> : <UserRound size={17} />}
      </div>
      <div className="message-content">
        <div className="message-bubble">
          {message.uploadedFile ? (
            <div className="message-file-note">
              <FileText size={14} />
              <span>{message.uploadedFile.filename}</span>
            </div>
          ) : null}
          <p>{message.content}</p>
        </div>
        {message.response ? (
          <AssistantResultCards
            response={message.response}
            indexingResult={indexingResult}
            indexingLoading={indexingLoading}
            indexingError={indexingError}
            onIndexSelected={onIndexSelected}
          />
        ) : null}
      </div>
    </article>
  );
}

function AssistantResultCards({
  response,
  indexingResult,
  indexingLoading,
  indexingError,
  onIndexSelected
}: {
  response: ChatApiResponse;
  indexingResult: SelectedResearchSourceIndexResponse | null;
  indexingLoading: boolean;
  indexingError: string | null;
  onIndexSelected: (sources: ResearchSource[]) => void;
}) {
  const assignment = artifactPayload<{ analysis: AssignmentAnalysis }>(response, "assignment_analysis")?.analysis ?? null;
  const noticeActions = artifactPayload<{ action_items: ActionItem[] }>(response, "notice_parse")?.action_items ?? [];
  const planner = artifactPayload<PlannerOutput>(response, "planner_output") ?? null;
  const execution = artifactPayload<MultiIntentExecutionPlan>(response, "multi_intent_execution") ?? null;
  const fitness = artifactPayload<FitnessPlanOutput>(response, "fitness_plan") ?? null;
  const social = artifactPayload<SocialContentOutput>(response, "social_content") ?? null;
  const arxivCandidates = artifactPayload<ArxivSourceCandidates>(response, "arxiv_source_candidates");
  const liveEmail = artifactPayload<{ draft?: EmailDraft } | EmailDraft>(response, "email_draft");
  const emailDraft = isEmailDraft(liveEmail) ? liveEmail : liveEmail?.draft ?? null;
  const hasCards = Boolean(
    assignment ||
      noticeActions.length ||
      planner ||
      execution ||
      fitness ||
      social ||
      arxivCandidates ||
      emailDraft ||
      response.missing_information.length ||
      response.next_actions.length
  );

  if (!hasCards) {
    return null;
  }

  return (
    <div className="assistant-result-stack">
      {response.missing_information.length ? (
        <div className="inline-result-card">
          <strong>Needs clarification</strong>
          <ul>
            {response.missing_information.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {assignment ? <AssignmentSummary assignment={assignment} /> : null}
      {noticeActions.length ? <NoticeActionReviewPanel actions={noticeActions} /> : null}
      {execution ? <ExecutionPlanPanel plan={execution} /> : null}
      {arxivCandidates ? (
        <ResearchReviewPanel
          sources={[]}
          arxivCandidates={arxivCandidates}
          indexingResult={indexingResult}
          indexingLoading={indexingLoading}
          indexingError={indexingError}
          onIndexSelected={onIndexSelected}
        />
      ) : null}
      {planner ? <TaskTimeline plan={planner} /> : null}
      {fitness ? <FitnessPlanPanel plan={fitness} /> : null}
      {emailDraft ? <EmailDraftCard draft={emailDraft} /> : null}
      {social ? <SocialContentPanel content={social} /> : null}
      {response.next_actions.length ? (
        <div className="inline-result-card">
          <strong>Next actions</strong>
          <ul>
            {response.next_actions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function ArtifactDetail({ response }: { response?: ChatApiResponse | null }) {
  if (!response) {
    return (
      <section className="panel detail-json-panel">
        <div className="panel-heading">
          <Bug size={18} />
          <h2>Artifacts</h2>
        </div>
        <p className="module-hint">Run a task to inspect raw artifacts and router output.</p>
      </section>
    );
  }

  return (
    <section className="panel detail-json-panel">
      <div className="panel-heading">
        <Bug size={18} />
        <h2>Artifacts</h2>
      </div>
      <div className="artifact-kind-list">
        {response.artifacts.map((artifact) => (
          <span key={`${artifact.kind}-${artifact.name}`}>{artifact.kind}</span>
        ))}
      </div>
      <details>
        <summary>Router output</summary>
        <pre>{JSON.stringify(response.router, null, 2)}</pre>
      </details>
      <details>
        <summary>Raw artifacts</summary>
        <pre>{JSON.stringify(response.artifacts, null, 2)}</pre>
      </details>
    </section>
  );
}

function artifactPayload<T>(response: ChatApiResponse | null, kind: string): T | null {
  const artifacts = response?.artifacts?.filter((item) => item.kind === kind) ?? [];
  const artifact = artifacts[artifacts.length - 1];
  return (artifact?.payload as T | undefined) ?? null;
}

function createConversationSession(index: number): ConversationSession {
  return {
    id: createConversationId(),
    title: `会话 ${index}`,
    activeMessage: "",
    uploadedFile: null,
    messages: [],
    chatResponse: null,
    traceQuery: "",
    traceWaterfall: null,
    researchIndexingResult: null
  };
}

function createConversationId(): string {
  const randomId = globalThis.crypto?.randomUUID?.();
  return randomId ? `conv_${randomId}` : `conv_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function createMessageId(prefix: string): string {
  const randomId = globalThis.crypto?.randomUUID?.();
  return randomId ? `${prefix}_${randomId}` : `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function latestResponse(session: ConversationSession): ChatApiResponse | null {
  const latest = [...session.messages].reverse().find((message) => message.response);
  return latest?.response ?? null;
}

function traceFromResponse(response?: ChatApiResponse | null): TraceStep[] {
  return response?.trace?.length
    ? response.trace.map((step) => ({
        name: step.name,
        detail: JSON.stringify(step.payload),
        status: "done"
      }))
    : [];
}

function deriveSessionTitle(session: ConversationSession, responseText: string, fallback: string): string {
  if (!/^会话 \d+$/.test(session.title)) {
    return session.title;
  }
  const source = fallback || responseText || session.id;
  const title = source.trim().replace(/\s+/g, " ").slice(0, 22);
  return title || session.title;
}

function isEmailDraft(value: unknown): value is EmailDraft {
  return Boolean(
    value &&
      typeof value === "object" &&
      "subject" in value &&
      "body" in value &&
      "recipient_type" in value
  );
}
