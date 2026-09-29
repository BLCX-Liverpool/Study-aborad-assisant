import { useMemo, useState } from "react";
import {
  AlertCircle,
  Brain,
  CalendarClock,
  CheckCircle2,
  Dumbbell,
  FileText,
  MessageSquareText,
  Send,
  SquarePen,
  Upload,
  Workflow
} from "lucide-react";
import { AssignmentSummary } from "./components/AssignmentSummary";
import { TaskTimeline } from "./components/TaskTimeline";
import { EmailDraftCard } from "./components/EmailDraftCard";
import { ExecutionPlanPanel } from "./components/ExecutionPlanPanel";
import { AgentTracePanel } from "./components/AgentTracePanel";
import { ChatComposer } from "./components/ChatComposer";
import { FileUploader } from "./components/FileUploader";
import { FitnessPlanPanel } from "./components/FitnessPlanPanel";
import { MemoryReviewPanel } from "./components/MemoryReviewPanel";
import { NoticeActionReviewPanel } from "./components/NoticeActionReviewPanel";
import { ResearchReviewPanel } from "./components/ResearchReviewPanel";
import { SocialContentPanel } from "./components/SocialContentPanel";
import { TraceWaterfallPanel } from "./components/TraceWaterfallPanel";
import {
  sampleAssignment,
  sampleEmail,
  sampleFitness,
  sampleIdeaVerification,
  sampleNoticeActions,
  samplePlan,
  sampleResearchSources,
  sampleSocialContent,
  sampleTrace
} from "./data/sample";
import {
  confirmMemoryCandidates,
  deleteMemories,
  fetchMemoryReview,
  fetchTraceWaterfall,
  indexSelectedArxivSources,
  planMultiIntent,
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
const defaultMessage = "帮我分析 coursework，并安排完成计划。";

type ConversationSession = {
  id: string;
  title: string;
  activeMessage: string;
  uploadedFile: UploadedFile | null;
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
  const [executionPlan, setExecutionPlan] = useState<MultiIntentExecutionPlan | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [memoryReview, setMemoryReview] = useState<MemoryReviewResponse | null>(null);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoryAction, setMemoryAction] = useState<MemoryDecisionResponse | null>(null);
  const [researchIndexingLoading, setResearchIndexingLoading] = useState(false);
  const [researchIndexingError, setResearchIndexingError] = useState<string | null>(null);

  const activeSession = sessions.find((session) => session.id === activeConversationId) ?? sessions[0];
  const uploadedFile = activeSession.uploadedFile;
  const activeMessage = activeSession.activeMessage;
  const chatResponse = activeSession.chatResponse;
  const traceQuery = activeSession.traceQuery;
  const traceWaterfall = activeSession.traceWaterfall;
  const researchIndexingResult = activeSession.researchIndexingResult;

  const liveAssignment = artifactPayload<{ analysis: AssignmentAnalysis }>(chatResponse, "assignment_analysis")?.analysis ?? sampleAssignment;
  const liveNoticeActions = artifactPayload<{ action_items: ActionItem[] }>(chatResponse, "notice_parse")?.action_items ?? sampleNoticeActions;
  const livePlanner = artifactPayload<PlannerOutput>(chatResponse, "planner_output") ?? samplePlan;
  const liveFitness = artifactPayload<FitnessPlanOutput>(chatResponse, "fitness_plan") ?? sampleFitness;
  const liveSocial = artifactPayload<SocialContentOutput>(chatResponse, "social_content") ?? sampleSocialContent;
  const arxivCandidates = artifactPayload<ArxivSourceCandidates>(chatResponse, "arxiv_source_candidates");
  const liveEmail = artifactPayload<{ draft?: EmailDraft } | EmailDraft>(chatResponse, "email_draft");
  const emailDraft = isEmailDraft(liveEmail) ? liveEmail : liveEmail?.draft ?? sampleEmail;
  const liveExecution = artifactPayload<MultiIntentExecutionPlan>(chatResponse, "multi_intent_execution") ?? executionPlan;
  const liveTrace: TraceStep[] = chatResponse?.trace?.length
    ? chatResponse.trace.map((step) => ({
        name: step.name,
        detail: JSON.stringify(step.payload),
        status: "done"
      }))
    : sampleTrace;

  const statusItems = useMemo(
    () => [
      { label: "Upload", value: uploadedFile ? "Ready" : "Optional", icon: Upload },
      { label: "Assignment", value: chatResponse ? "Live linked" : "Sample loaded", icon: FileText },
      { label: "Planner", value: `${livePlanner.tasks.length} tasks`, icon: CalendarClock },
      { label: "Fitness", value: `${liveFitness.workout_days.length} days`, icon: Dumbbell },
      { label: "Social", value: `${liveSocial.drafts.length} drafts`, icon: SquarePen },
      { label: "Memory", value: `${memoryReview?.candidates.length ?? 0} pending`, icon: Brain }
    ],
    [
      uploadedFile,
      chatResponse,
      livePlanner.tasks.length,
      liveFitness.workout_days.length,
      liveSocial.drafts.length,
      memoryReview?.candidates.length
    ]
  );

  function updateSession(sessionId: string, patch: Partial<ConversationSession>) {
    setSessions((current) =>
      current.map((session) => (session.id === sessionId ? { ...session, ...patch } : session))
    );
  }

  function updateActiveSession(patch: Partial<ConversationSession>) {
    updateSession(activeSession.id, patch);
  }

  function startNewConversation() {
    const session = createConversationSession(sessions.length + 1);
    setSessions((current) => [session, ...current]);
    setActiveConversationId(session.id);
    setChatError(null);
    setWorkflowError(null);
    setTraceError(null);
    setResearchIndexingError(null);
  }

  async function runChat() {
    const session = activeSession;
    setChatLoading(true);
    setChatError(null);
    try {
      const response = await sendChatMessage({
        userId,
        message: session.activeMessage,
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
      updateSession(session.id, {
        chatResponse: response,
        title: deriveSessionTitle(session, response.final_response),
        traceQuery: response.trace_id,
        researchIndexingResult: null
      });
      const execution = artifactPayload<MultiIntentExecutionPlan>(response, "multi_intent_execution");
      if (execution) {
        setExecutionPlan(execution);
      }
      await loadTraceWaterfall(response.trace_id, session.id);
      await loadMemoryReview();
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "Chat request failed");
    } finally {
      setChatLoading(false);
    }
  }

  async function runExecutionPlan() {
    setWorkflowLoading(true);
    setWorkflowError(null);
    try {
      const plan = await planMultiIntent({
        user_id: userId,
        message: activeSession.activeMessage,
        structured_intents: activeSession.chatResponse?.router?.structured_intents ?? []
      });
      setExecutionPlan(plan);
    } catch (error) {
      setWorkflowError(error instanceof Error ? error.message : "Execution planning failed");
    } finally {
      setWorkflowLoading(false);
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
      updateSession(sessionId, { traceWaterfall: waterfall, traceQuery: normalized });
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
      updateSession(session.id, { researchIndexingResult: result });
    } catch (error) {
      setResearchIndexingError(error instanceof Error ? error.message : "ArXiv indexing failed");
    } finally {
      setResearchIndexingLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Study Abroad Assistant</p>
          <h1>Academic planning workspace</h1>
        </div>
        <div className="topbar-actions">
          <span className="status-pill">
            <CheckCircle2 size={16} />
            Phase 12 enhanced
          </span>
        </div>
      </header>

      <section className="status-grid" aria-label="Workflow status">
        {statusItems.map((item) => (
          <div className="status-tile" key={item.label}>
            <item.icon size={18} />
            <div>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          </div>
        ))}
      </section>

      <section className="workspace-grid">
        <aside className="left-pane" aria-label="Input workspace">
          <div className="panel conversation-panel">
            <div className="panel-heading action-heading">
              <MessageSquareText size={18} />
              <h2>Conversations</h2>
              <button className="icon-button" type="button" onClick={startNewConversation} title="New conversation">
                <SquarePen size={16} />
              </button>
            </div>
            <div className="conversation-list" aria-label="Conversation list">
              {sessions.map((session) => (
                <button
                  className={session.id === activeSession.id ? "conversation-item active" : "conversation-item"}
                  key={session.id}
                  type="button"
                  onClick={() => {
                    setActiveConversationId(session.id);
                    setChatError(null);
                    setWorkflowError(null);
                    setTraceError(null);
                    setResearchIndexingError(null);
                  }}
                >
                  <span>{session.title}</span>
                  <small>{session.id}</small>
                </button>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-heading">
              <MessageSquareText size={18} />
              <h2>Chat</h2>
            </div>
            <ChatComposer
              value={activeMessage}
              onChange={(value) => updateActiveSession({ activeMessage: value })}
              onRun={runChat}
              loading={chatLoading}
              response={chatResponse}
              error={chatError}
            />
          </div>

          <div className="panel">
            <div className="panel-heading">
              <Upload size={18} />
              <h2>Upload</h2>
            </div>
            <FileUploader
              userId={userId}
              conversationId={activeSession.id}
              onUploaded={(file) => updateActiveSession({ uploadedFile: file })}
            />
            {uploadedFile ? (
              <div className="uploaded-file">
                <FileText size={16} />
                <span>{uploadedFile.filename}</span>
              </div>
            ) : null}
          </div>

          <div className="panel">
            <div className="panel-heading">
              <Workflow size={18} />
              <h2>Workflow</h2>
            </div>
            <button className="secondary-button" type="button" onClick={runExecutionPlan} disabled={workflowLoading}>
              <Workflow size={16} />
              {workflowLoading ? "Planning..." : "Plan execution"}
            </button>
            {workflowError ? <p className="error-text">{workflowError}</p> : null}
          </div>
        </aside>

        <section className="main-pane" aria-label="Analysis workspace">
          <AssignmentSummary assignment={liveAssignment} />
          <NoticeActionReviewPanel actions={liveNoticeActions} />
          {liveExecution ? <ExecutionPlanPanel plan={liveExecution} /> : null}
          <ResearchReviewPanel
            sources={sampleResearchSources}
            verification={sampleIdeaVerification}
            arxivCandidates={arxivCandidates}
            indexingResult={researchIndexingResult}
            indexingLoading={researchIndexingLoading}
            indexingError={researchIndexingError}
            onIndexSelected={runIndexSelectedArxivSources}
          />
          <TaskTimeline plan={livePlanner} />
          <FitnessPlanPanel plan={liveFitness} />
        </section>

        <aside className="right-pane" aria-label="Agent trace and email workspace">
          <AgentTracePanel trace={liveTrace} />
          <TraceWaterfallPanel
            traceId={traceQuery || chatResponse?.trace_id || ""}
            onTraceIdChange={(value) => updateActiveSession({ traceQuery: value })}
            onLookup={() => loadTraceWaterfall()}
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
          <EmailDraftCard draft={emailDraft} />
          <SocialContentPanel content={liveSocial} />
          <div className="panel notice-panel">
            <div className="panel-heading">
              <AlertCircle size={18} />
              <h2>Approval Gate</h2>
            </div>
            <p>
              Email sending, deletion, payment, and real calendar writes require explicit user
              approval. This MVP only prepares local drafts and plans.
            </p>
            <button className="secondary-button" type="button">
              <Send size={16} />
              Send disabled
            </button>
          </div>
        </aside>
      </section>

      <footer className="footer-line">
        <Workflow size={16} />
        <span>{activeMessage}</span>
      </footer>
    </main>
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
    activeMessage: defaultMessage,
    uploadedFile: null,
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

function deriveSessionTitle(session: ConversationSession, responseText: string): string {
  if (!/^会话 \d+$/.test(session.title)) {
    return session.title;
  }
  const source = session.activeMessage || responseText || session.id;
  const title = source.trim().replace(/\s+/g, " ").slice(0, 18);
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
