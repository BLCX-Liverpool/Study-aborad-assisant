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
  memory_context?: Record<string, unknown> | null;
  missing_information: string[];
  next_actions: string[];
};

export type MultiIntentExecutionPlan = {
  summary: string;
  steps: Array<{
    index: number;
    intent_name: string;
    agent_intent: string;
    status: "planned" | "completed" | "needs_input" | "skipped" | "blocked";
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
  assumptions: string[];
  disclaimer: string;
};
