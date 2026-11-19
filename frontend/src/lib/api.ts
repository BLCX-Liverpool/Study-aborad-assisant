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
      "Idempotency-Key": idempotencyKey
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

export async function fetchWorkflow(workflow: WorkflowAccepted, userId: string): Promise<WorkflowView> {
  const response = await fetch(`${workflow.status_url}?user_id=${encodeURIComponent(userId)}`);
  if (!response.ok) {
    throw new Error(`Workflow lookup failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchWorkflowArtifacts(
  workflow: WorkflowAccepted,
  userId: string
): Promise<WorkflowArtifactView[]> {
  const response = await fetch(
    `${workflow.status_url}/artifacts?user_id=${encodeURIComponent(userId)}`
  );
  if (!response.ok) {
    throw new Error(`Workflow artifact lookup failed: ${response.status}`);
  }
  return response.json();
}

export function waitForWorkflow(
  workflow: WorkflowAccepted,
  userId: string,
  onProgress?: (eventName: string) => void
): Promise<ChatApiResponse> {
  return new Promise((resolve, reject) => {
    const url = `${workflow.events_url}?user_id=${encodeURIComponent(userId)}`;
    const source = new EventSource(url);
    let settled = false;
    const finish = async (eventName: string) => {
      if (settled) return;
      settled = true;
      source.close();
      try {
        const [state, artifacts] = await Promise.all([
          fetchWorkflow(workflow, userId),
          fetchWorkflowArtifacts(workflow, userId)
        ]);
        resolve(workflowAsChatResponse(state, artifacts));
      } catch (error) {
        reject(error);
      }
      onProgress?.(eventName);
    };
    const progressEvents = [
      "workflow.created",
      "workflow.planning",
      "workflow.running",
      "step.queued",
      "step.started",
      "step.retry_wait",
      "step.completed",
      "artifact.created"
    ];
    for (const name of progressEvents) {
      source.addEventListener(name, () => onProgress?.(name));
    }
    for (const name of [
      "workflow.completed",
      "workflow.partial_failed",
      "workflow.failed",
      "workflow.cancelled",
      "workflow.dead_lettered",
      "workflow.waiting_input"
    ]) {
      source.addEventListener(name, () => void finish(name));
    }
    source.onerror = () => {
      if (!settled && source.readyState === EventSource.CLOSED) {
        reject(new Error("Workflow event stream closed before a terminal status was received"));
      }
    };
  });
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
