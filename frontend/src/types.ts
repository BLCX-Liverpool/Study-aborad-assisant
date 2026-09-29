export type EvidenceRef = {
  source_file_id?: string | null;
  source_name?: string | null;
  page?: number | null;
  slide?: number | null;
  section?: string | null;
  quote?: string | null;
  start_char?: number | null;
  end_char?: number | null;
  confidence: number;
};

export type AssignmentRequirement = {
  requirement_type: string;
  content: string;
  evidence: EvidenceRef[];
};

export type AssignmentAnalysis = {
  course_code?: string | null;
  title?: string | null;
  objective: string;
  deliverables: string[];
  deadline?: string | null;
  marking_criteria: AssignmentRequirement[];
  constraints: AssignmentRequirement[];
  missing_information: string[];
  possible_ideas: string[];
  suggested_structure: string[];
  research_queries: string[];
  research_sources: EvidenceRef[];
};

export type PlannedTask = {
  title: string;
  description?: string | null;
  source_type: string;
  source_id?: string | null;
  start_time?: string | null;
  deadline?: string | null;
  estimated_minutes?: number | null;
  priority: "low" | "medium" | "high" | "urgent";
  status: "todo" | "in_progress" | "done" | "cancelled";
  evidence: EvidenceRef[];
};

export type PlannerOutput = {
  tasks: PlannedTask[];
  events: Array<{
    title: string;
    description?: string | null;
    start_time?: string | null;
    end_time?: string | null;
  }>;
  reminders: Array<{
    title: string;
    remind_at: string;
    channel: string;
    task_title?: string | null;
  }>;
  conflicts: string[];
  assumptions: string[];
  selected_strategy?: string | null;
  planning_candidates?: Array<{
    strategy: string;
    task_count: number;
    event_count: number;
    conflict_count: number;
    score: {
      conflict_penalty: number;
      deadline_safety: number;
      priority_alignment: number;
      preference_alignment: number;
      workload_balance: number;
      evidence_alignment: number;
      total: number;
    };
    assumptions: string[];
  }>;
  thought_trace?: Array<{
    step: "generate" | "evaluate" | "select";
    strategy: string;
    rationale: string;
    score?: {
      conflict_penalty: number;
      deadline_safety: number;
      priority_alignment: number;
      preference_alignment: number;
      workload_balance: number;
      evidence_alignment: number;
      total: number;
    } | null;
  }>;
};

export type ActionItem = {
  action_type: string;
  title: string;
  description?: string | null;
  source_type: string;
  source_id?: string | null;
  deadline?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  estimated_minutes?: number | null;
  priority: "low" | "medium" | "high" | "urgent";
  evidence: EvidenceRef[];
};

export type ResearchSource = {
  source_type: "arxiv" | "web" | "paper_pdf";
  title: string;
  url: string;
  summary?: string | null;
  authors: string[];
  published_at?: string | null;
  evidence: EvidenceRef[];
  metadata: Record<string, unknown>;
};

export type ArxivSourceCandidates = {
  status: "needs_user_selection" | string;
  queries: string[];
  sources: ResearchSource[];
  assumptions: string[];
};

export type SelectedResearchSourceIndexResponse = {
  user_id: string;
  indexed_file_ids: string[];
  results: Array<{
    source: ResearchSource;
    file_id: string;
    local_path?: string | null;
    status: "indexed" | "download_failed" | "index_failed" | "skipped";
    error?: string | null;
    index?: {
      file_id: string;
      chunk_count: number;
      embedding_count: number;
      status: string;
    } | null;
  }>;
  assumptions: string[];
};

export type IdeaVerificationResponse = {
  findings: Array<{
    idea: string;
    status: "supported" | "needs_more_evidence" | "conflicts_with_constraints";
    reasons: string[];
    supporting_sources: string[];
  }>;
  recommended_ideas: string[];
};

export type EmailDraft = {
  recipient_type: string;
  subject: string;
  body: string;
  tone: string;
  missing_information: string[];
  requires_user_approval: boolean;
};

export type TraceStep = {
  name: string;
  detail: string;
  status: "idle" | "running" | "done" | "blocked";
};

export type UploadedFile = {
  file_id: string;
  filename: string;
  mime_type?: string | null;
  source_type: string;
  storage_path: string;
  checksum: string;
  status: string;
};

export type ChatApiResponse = {
  user_id: string;
  conversation_id: string;
  trace_id: string;
  router: {
    primary_intent: string;
    secondary_intents: string[];
    confidence: number;
    structured_intents: Array<{
      name: string;
      agent_intent: string;
      slots: Record<string, unknown>;
      condition?: string | null;
      depends_on: number[];
      missing_slots: string[];
      confidence: number;
      source: string;
    }>;
    clarification_questions: string[];
    fusion_metadata: Record<string, unknown>;
  };
  final_response: string;
  artifacts: Array<{
    name: string;
    kind: string;
    payload: Record<string, unknown>;
  }>;
  trace: Array<{
    name: string;
    payload: Record<string, unknown>;
  }>;
  latency_summary?: LatencyTraceSummary | null;
  memory_context?: Record<string, unknown> | null;
  missing_information: string[];
  next_actions: string[];
};

export type LatencyTraceSummary = {
  trace_id: string;
  total_duration_ms: number;
  span_count: number;
  failed_span_count: number;
  by_type: Record<string, number>;
  slowest_spans: Array<{
    span_name: string;
    span_type: string;
    duration_ms: number;
    status: "completed" | "failed";
  }>;
  persisted: boolean;
};

export type TraceSpanView = {
  span_id: string;
  trace_id: string;
  parent_span_id?: string | null;
  user_id?: string | null;
  conversation_id?: string | null;
  agent_run_id?: string | null;
  span_name: string;
  span_type: string;
  status: string;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  offset_ms: number;
  depth: number;
  input_json?: Record<string, unknown> | null;
  output_json?: Record<string, unknown> | null;
  error?: string | null;
  metadata_json: Record<string, unknown>;
};

export type TraceWaterfallResponse = {
  trace_id: string;
  found: boolean;
  summary?: LatencyTraceSummary | null;
  spans: TraceSpanView[];
};

export type LongTermMemoryItem = {
  id?: string | null;
  namespace: string;
  memory_type: string;
  content: string;
  score: number;
  source_type?: string | null;
  source_id?: string | null;
  confidence?: number | null;
  access_policy?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type MemoryReviewResponse = {
  user_id: string;
  memories: LongTermMemoryItem[];
  candidates: LongTermMemoryItem[];
};

export type MemoryDecisionResponse = {
  status: string;
  memory_ids: string[];
  assumptions: string[];
  error?: string | null;
};

export type MultiIntentExecutionPlan = {
  summary: string;
  steps: Array<{
    index: number;
    intent_name: string;
    agent_intent: string;
    status: "planned" | "completed" | "needs_input" | "skipped" | "blocked" | "failed";
    depends_on: number[];
    condition?: string | null;
    slots: Record<string, unknown>;
    missing_slots: string[];
    result_summary?: string | null;
  }>;
  planner_output?: PlannerOutput | null;
  email_reminder_drafts: PlannerOutput["reminders"];
  assumptions: string[];
  unsupported_intents: string[];
};

export type WorkoutBlock = {
  name: string;
  duration_minutes: number;
  intensity: "low" | "moderate" | "high";
  instructions: string[];
};

export type WorkoutDay = {
  day_of_week: string;
  focus: string;
  duration_minutes: number;
  blocks: WorkoutBlock[];
  safety_notes: string[];
};

export type FitnessPlanOutput = {
  summary: string;
  workout_days: WorkoutDay[];
  habit_tasks: PlannedTask[];
  schedule_tasks: PlannedTask[];
  progression: Array<{
    week: number;
    focus: string;
    progression_rule: string;
    deload_or_review?: string | null;
  }>;
  memory_candidates: Array<{
    namespace: string;
    content: string;
    requires_confirmation: boolean;
    confirmed: boolean;
  }>;
  memory_confirmation?: {
    status: string;
    candidate_count: number;
    pending_memory_ids: string[];
    confirmed_memory_ids: string[];
    skipped: string[];
    assumptions: string[];
    error?: string | null;
  } | null;
  missing_information: string[];
  risk_notes: string[];
  assumptions: string[];
  disclaimer: string;
};

export type SocialContentDraft = {
  platform: string;
  variant: string;
  title?: string | null;
  body: string;
  hashtags: string[];
  call_to_action?: string | null;
  platform_fit_notes: string[];
};

export type SocialContentOutput = {
  summary: string;
  drafts: SocialContentDraft[];
  safety: {
    level: "ok" | "needs_review" | "blocked";
    issues: string[];
    redactions: string[];
  };
  platform_standard?: {
    platform: string;
    recommended_length: string;
    structure: string[];
    tone_notes: string[];
    privacy_rules: string[];
  } | null;
  platform_notes: string[];
  image_generation_tool?: {
    tool_name: string;
    status: string;
    boundary: string;
    expected_inputs: string[];
  } | null;
  memory_candidates: Array<{
    namespace: string;
    content: string;
    requires_confirmation: boolean;
    confirmed: boolean;
  }>;
  memory_confirmation?: {
    status: string;
    candidate_count: number;
    pending_memory_ids: string[];
    confirmed_memory_ids: string[];
    skipped: string[];
    assumptions: string[];
    error?: string | null;
  } | null;
  assumptions: string[];
  disclaimer: string;
};
