import type {
  ChatApiResponse,
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
  UploadedFile
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
}): Promise<ChatApiResponse> {
  const response = await fetch(`${API_PREFIX}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: params.userId,
      conversation_id: params.conversationId,
      message: params.message,
      agent_inputs: params.agentInputs ?? {},
      persist_agent_runs: true
    })
  });

  if (!response.ok) {
    throw new Error(`Chat failed: ${response.status}`);
  }

  return response.json();
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
