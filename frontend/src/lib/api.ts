import type {
  ChatApiResponse,
  ChatSubmissionResponse,
  ActionItem,
  EmailDraft,
  FitnessPlanOutput,
  MemoryDecisionResponse,
  MemoryReviewResponse,
  MultiIntentExecutionPlan,
  PlannerOutput,
  ResearchSource,
  SelectedResearchSourceIndexResponse,
  SocialContentOutput,
  TraceWaterfallResponse,
  UploadedFile,
  WorkflowAccepted,
  WorkflowArtifactView,
  WorkflowView
} from "../types";

const API_PREFIX = "/api";
let cachedAuthToken = "";

async function authHeaders(extra: Record<string, string> = {}): Promise<Record<string, string>> {
  let token = cachedAuthToken || sessionStorage.getItem("study_access_token") || "";
  if (!token && import.meta.env.DEV && import.meta.env.VITE_AUTH_TOKEN) {
    token = import.meta.env.VITE_AUTH_TOKEN;
  }
  if (!token && import.meta.env.DEV) {
    const response = await fetch(`${API_PREFIX}/auth/development-token?user_id=local_user`, { method: "POST" });
    if (response.ok) token = (await response.json()).access_token;
  }
  if (token) {
    cachedAuthToken = token;
    sessionStorage.setItem("study_access_token", token);
  }
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

export async function uploadFile(params: {
  file: File;
  userId: string;
  conversationId?: string;
  sourceType?: string;
}): Promise<UploadedFile> {
  const formData = new FormData();
  formData.append("file", params.file);
  formData.append("user_id", params.userId);
  if (params.conversationId) {
    formData.append("conversation_id", params.conversationId);
  }
  formData.append("source_type", params.sourceType ?? "uploaded_document");

  const response = await fetch(`${API_PREFIX}/files`, {
    method: "POST",
    body: formData
  });

  if (!response.ok) {
    throw new Error(`Upload failed: ${response.status}`);
  }

  return response.json();
}

export async function createEmailDraft(params: {
  userId: string;
  purpose: string;
  recipientHint?: string;
  additionalContext?: string;
}): Promise<EmailDraft> {
  const response = await fetch(`${API_PREFIX}/email/drafts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: params.userId,
      purpose: params.purpose,
      recipient_hint: params.recipientHint,
      context: {
        additional_context: params.additionalContext
      },
      language: "en"
    })
  });

  if (!response.ok) {
    throw new Error(`Email draft failed: ${response.status}`);
  }

  const payload = await response.json();
  return payload.draft;
}

export async function planAssignment(body: unknown): Promise<PlannerOutput> {
  const response = await fetch(`${API_PREFIX}/planner/assignment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`Planning failed: ${response.status}`);
  }

  return response.json();
}

export async function sendChatMessage(params: {
  userId: string;
  message: string;
  conversationId?: string;
  agentInputs?: Record<string, unknown>;
}): Promise<ChatSubmissionResponse> {
  const idempotencyKey = globalThis.crypto?.randomUUID?.() ?? `chat-${Date.now()}-${Math.random()}`;
  const response = await fetch(`${API_PREFIX}/v2/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
      ...(await authHeaders())
    },
    body: JSON.stringify({
      user_id: params.userId,
      conversation_id: params.conversationId,
      message: params.message,
      agent_inputs: params.agentInputs ?? {},
      persist_agent_runs: true,
      execution_mode: "auto"
    })
  });

  if (!response.ok) {
    throw new Error(`Chat failed: ${response.status}`);
  }

  return response.json();
}

export async function fetchWorkflow(workflow: WorkflowAccepted): Promise<WorkflowView> {
  const response = await fetch(workflow.status_url, { headers: await authHeaders() });
  if (!response.ok) {
    throw new Error(`Workflow lookup failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchWorkflowArtifacts(
  workflow: WorkflowAccepted,
  _userId?: string
): Promise<WorkflowArtifactView[]> {
  const response = await fetch(`${workflow.status_url}/artifacts`, { headers: await authHeaders() });
  if (!response.ok) {
    throw new Error(`Workflow artifact lookup failed: ${response.status}`);
  }
  return response.json();
}

export function waitForWorkflow(
  workflow: WorkflowAccepted,
  _userId: string,
  onProgress?: (eventName: string, state?: WorkflowView, artifacts?: WorkflowArtifactView[]) => void,
  afterEventId?: string
): Promise<ChatApiResponse> {
  return streamWorkflow(workflow, onProgress, afterEventId);
}

export class WorkflowNeedsInputError extends Error {
  constructor(
    public workflow: WorkflowAccepted,
    public state: WorkflowView,
    public artifacts: WorkflowArtifactView[],
    public lastEventId?: string
  ) {
    super("Workflow is waiting for additional information");
  }
}

async function streamWorkflow(
  workflow: WorkflowAccepted,
  onProgress?: (eventName: string, state?: WorkflowView, artifacts?: WorkflowArtifactView[]) => void,
  afterEventId?: string
): Promise<ChatApiResponse> {
  const headers = await authHeaders({ Accept: "text/event-stream" });
  if (afterEventId) headers["Last-Event-ID"] = afterEventId;
  const response = await fetch(workflow.events_url, {
    headers
  });
  if (!response.ok || !response.body) throw new Error(`Workflow stream failed: ${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const terminal = new Set([
    "workflow.completed", "workflow.partial_failed", "workflow.failed",
    "workflow.cancelled", "workflow.dead_lettered", "workflow.waiting_input"
  ]);
  let lastEventId = afterEventId;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const eventName = block.split("\n").find((line) => line.startsWith("event:"))?.slice(6).trim();
      lastEventId = block.split("\n").find((line) => line.startsWith("id:"))?.slice(3).trim() || lastEventId;
      if (eventName) {
        const [state, artifacts] = await Promise.all([
          fetchWorkflow(workflow), fetchWorkflowArtifacts(workflow)
        ]);
        onProgress?.(eventName, state, artifacts);
        if (terminal.has(eventName)) {
          await reader.cancel();
          if (eventName === "workflow.waiting_input") {
            throw new WorkflowNeedsInputError(workflow, state, artifacts, lastEventId);
          }
          return workflowAsChatResponse(state, artifacts);
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
  const state = await fetchWorkflow(workflow);
  const artifacts = await fetchWorkflowArtifacts(workflow);
  if (state.status === "waiting_input") throw new WorkflowNeedsInputError(workflow, state, artifacts, lastEventId);
  if (["completed", "partial_failed", "failed", "cancelled", "dead_lettered"].includes(state.status)) {
    return workflowAsChatResponse(state, artifacts);
  }
  throw new Error("Workflow event stream closed before a terminal status was received");
}

export async function submitWorkflowInput(
  workflow: WorkflowAccepted,
  stepId: string,
  agent: string,
  values: Record<string, unknown>
): Promise<void> {
  const response = await fetch(`${workflow.status_url}/inputs`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ step_id: stepId, agent_inputs: { [agent]: values } })
  });
  if (!response.ok) throw new Error(`Workflow input submission failed: ${response.status}`);
}

function workflowAsChatResponse(
  workflow: WorkflowView,
  artifacts: WorkflowArtifactView[]
): ChatApiResponse {
  return {
    mode: "sync",
    user_id: workflow.user_id,
    conversation_id: workflow.conversation_id ?? workflow.id,
    trace_id: workflow.trace_id,
    router: {
      primary_intent: "async_workflow",
      secondary_intents: [],
      confidence: 1,
      structured_intents: [],
      clarification_questions: [],
      fusion_metadata: { workflow_id: workflow.id }
    },
    final_response:
      workflow.final_response ??
      (workflow.steps.map((step) => step.result_summary).filter(Boolean).join("\n\n") ||
        `Workflow ${workflow.status}`),
    artifacts: artifacts.map((artifact) => ({
      name: artifact.name,
      kind: artifact.kind,
      payload: artifact.payload ?? { storage_uri: artifact.storage_uri }
    })),
    trace: workflow.steps.map((step) => ({
      name: `worker.${step.agent_intent}.${step.status}`,
      payload: {
        step_id: step.id,
        attempt_count: step.attempt_count,
        error: step.last_error_message
      }
    })),
    memory_context: null,
    missing_information: workflow.steps.flatMap((step) => step.missing_information),
    next_actions: []
  };
}

export async function createFitnessPlan(body: unknown): Promise<FitnessPlanOutput> {
  const response = await fetch(`${API_PREFIX}/fitness/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`Fitness planning failed: ${response.status}`);
  }

  return response.json();
}

export async function createSocialContent(body: unknown): Promise<SocialContentOutput> {
  const response = await fetch(`${API_PREFIX}/social-content/drafts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`Social content draft failed: ${response.status}`);
  }

  return response.json();
}

export async function parseNotice(body: unknown): Promise<{ action_items: ActionItem[]; missing_information: string[]; assumptions: string[] }> {
  const response = await fetch(`${API_PREFIX}/notice/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`Notice parse failed: ${response.status}`);
  }

  return response.json();
}

export async function planMultiIntent(body: unknown): Promise<MultiIntentExecutionPlan> {
  const response = await fetch(`${API_PREFIX}/execution/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`Execution planning failed: ${response.status}`);
  }

  return response.json();
}

export async function fetchTraceWaterfall(traceId: string): Promise<TraceWaterfallResponse> {
  const response = await fetch(`${API_PREFIX}/observability/traces/${encodeURIComponent(traceId)}/waterfall`);

  if (!response.ok) {
    throw new Error(`Trace lookup failed: ${response.status}`);
  }

  return response.json();
}

export async function fetchMemoryReview(userId: string): Promise<MemoryReviewResponse> {
  const response = await fetch(`${API_PREFIX}/memory/review?user_id=${encodeURIComponent(userId)}`);

  if (!response.ok) {
    throw new Error(`Memory review failed: ${response.status}`);
  }

  return response.json();
}

export async function confirmMemoryCandidates(userId: string, memoryIds: string[]): Promise<MemoryDecisionResponse> {
  return postMemoryDecision("/memory/candidates/confirm", userId, memoryIds, "Memory confirm failed");
}

export async function rejectMemoryCandidates(userId: string, memoryIds: string[]): Promise<MemoryDecisionResponse> {
  return postMemoryDecision("/memory/candidates/reject", userId, memoryIds, "Memory reject failed");
}

export async function deleteMemories(userId: string, memoryIds: string[]): Promise<MemoryDecisionResponse> {
  return postMemoryDecision("/memory/delete", userId, memoryIds, "Memory delete failed");
}

export async function indexSelectedArxivSources(params: {
  userId: string;
  sources: ResearchSource[];
  conversationId?: string;
  traceId?: string;
}): Promise<SelectedResearchSourceIndexResponse> {
  const response = await fetch(`${API_PREFIX}/assignment/research/index-selected-arxiv`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: params.userId,
      sources: params.sources,
      conversation_id: params.conversationId,
      trace_id: params.traceId
    })
  });

  if (!response.ok) {
    throw new Error(`ArXiv indexing failed: ${response.status}`);
  }

  return response.json();
}

async function postMemoryDecision(
  path: string,
  userId: string,
  memoryIds: string[],
  errorPrefix: string
): Promise<MemoryDecisionResponse> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: userId,
      memory_ids: memoryIds
    })
  });

  if (!response.ok) {
    throw new Error(`${errorPrefix}: ${response.status}`);
  }

  return response.json();
}
