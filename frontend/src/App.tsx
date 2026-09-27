import { useMemo, useState } from "react";
import {
  AlertCircle,
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
import { NoticeActionReviewPanel } from "./components/NoticeActionReviewPanel";
import { ResearchReviewPanel } from "./components/ResearchReviewPanel";
import { SocialContentPanel } from "./components/SocialContentPanel";
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
import { planMultiIntent, sendChatMessage } from "./lib/api";
import type {
  ActionItem,
  AssignmentAnalysis,
  ChatApiResponse,
  EmailDraft,
  FitnessPlanOutput,
  MultiIntentExecutionPlan,
  PlannerOutput,
  SocialContentOutput,
  TraceStep,
  UploadedFile
} from "./types";

const userId = "local_user";

export function App() {
  const [uploadedFile, setUploadedFile] = useState<UploadedFile | null>(null);
  const [activeMessage, setActiveMessage] = useState(
    "帮我分析 coursework，并安排完成计划。"
  );
  const [chatResponse, setChatResponse] = useState<ChatApiResponse | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [executionPlan, setExecutionPlan] = useState<MultiIntentExecutionPlan | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);

  const liveAssignment = artifactPayload<{ analysis: AssignmentAnalysis }>(chatResponse, "assignment_analysis")?.analysis ?? sampleAssignment;
  const liveNoticeActions = artifactPayload<{ action_items: ActionItem[] }>(chatResponse, "notice_parse")?.action_items ?? sampleNoticeActions;
  const livePlanner = artifactPayload<PlannerOutput>(chatResponse, "planner_output") ?? samplePlan;
  const liveFitness = artifactPayload<FitnessPlanOutput>(chatResponse, "fitness_plan") ?? sampleFitness;
  const liveSocial = artifactPayload<SocialContentOutput>(chatResponse, "social_content") ?? sampleSocialContent;
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
      { label: "Social", value: `${liveSocial.drafts.length} drafts`, icon: SquarePen }
    ],
    [uploadedFile, chatResponse, livePlanner.tasks.length, liveFitness.workout_days.length, liveSocial.drafts.length]
  );

  async function runChat() {
    setChatLoading(true);
    setChatError(null);
    try {
      const response = await sendChatMessage({
        userId,
        message: activeMessage,
        conversationId: chatResponse?.conversation_id,
        agentInputs: uploadedFile
          ? {
              assignment: {
                file_id: uploadedFile.file_id,
                source_path: uploadedFile.storage_path,
                source_name: uploadedFile.filename,
                mime_type: uploadedFile.mime_type
              }
            }
          : {}
      });
      setChatResponse(response);
      const execution = artifactPayload<MultiIntentExecutionPlan>(response, "multi_intent_execution");
      if (execution) {
        setExecutionPlan(execution);
      }
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
        message: activeMessage,
        structured_intents: chatResponse?.router?.structured_intents ?? []
      });
      setExecutionPlan(plan);
    } catch (error) {
      setWorkflowError(error instanceof Error ? error.message : "Execution planning failed");
    } finally {
      setWorkflowLoading(false);
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
          <div className="panel">
            <div className="panel-heading">
              <MessageSquareText size={18} />
              <h2>Chat</h2>
            </div>
            <ChatComposer
              value={activeMessage}
              onChange={setActiveMessage}
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
            <FileUploader userId={userId} onUploaded={setUploadedFile} />
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
          <ResearchReviewPanel sources={sampleResearchSources} verification={sampleIdeaVerification} />
          <TaskTimeline plan={livePlanner} />
          <FitnessPlanPanel plan={liveFitness} />
        </section>

        <aside className="right-pane" aria-label="Agent trace and email workspace">
          <AgentTracePanel trace={liveTrace} />
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
  const artifact = response?.artifacts?.find((item) => item.kind === kind);
  return (artifact?.payload as T | undefined) ?? null;
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
