import type {
  AssignmentAnalysis,
  ActionItem,
  EmailDraft,
  FitnessPlanOutput,
  IdeaVerificationResponse,
  PlannerOutput,
  ResearchSource,
  SocialContentOutput,
  TraceStep
} from "../types";

export const sampleAssignment: AssignmentAnalysis = {
  course_code: "COMP702",
  title: "Individual Research Report",
  objective: "Analyse a chosen AI system and produce a structured academic report.",
  deliverables: ["3000-word report", "Reference list", "Submission through university portal"],
  deadline: "2026-10-10T16:00:00Z",
  marking_criteria: [
    {
      requirement_type: "marking_criteria",
      content: "Argument quality and use of evidence are central to the grade.",
      evidence: [
        {
          source_file_id: "file_sample",
          source_name: "Coursework Brief.pdf",
          page: 3,
          section: "Marking Criteria",
          quote: "Use evidence to support the core argument.",
          confidence: 0.92
        }
      ]
    }
  ],
  constraints: [
    {
      requirement_type: "word_limit",
      content: "Maximum length is 3000 words.",
      evidence: [
        {
          source_file_id: "file_sample",
          source_name: "Coursework Brief.pdf",
          page: 2,
          section: "Submission Requirements",
          quote: "Report maximum length is 3000 words.",
          confidence: 0.95
        }
      ]
    }
  ],
  missing_information: ["Confirm whether appendices count toward the word limit."],
  possible_ideas: ["Evaluate a student-facing RAG assistant for coursework planning."],
  suggested_structure: ["Introduction", "System overview", "Evaluation", "Risks", "Conclusion"],
  research_queries: ["RAG evaluation education", "AI assistant academic integrity"],
  research_sources: []
};

export const samplePlan: PlannerOutput = {
  tasks: [
    {
      title: "COMP702: Understand requirements",
      description: "Read objective, deliverables, constraints, and missing information.",
      source_type: "assignment",
      source_id: "file_sample",
      start_time: "2026-10-01T08:30:00Z",
      deadline: "2026-10-01T10:00:00Z",
      estimated_minutes: 90,
      priority: "high",
      status: "todo",
      evidence: []
    },
    {
      title: "COMP702: Draft assignment",
      description: "Create the main draft based on the suggested structure and marking criteria.",
      source_type: "assignment",
      source_id: "file_sample",
      start_time: "2026-10-07T12:00:00Z",
      deadline: "2026-10-07T16:00:00Z",
      estimated_minutes: 240,
      priority: "high",
      status: "todo",
      evidence: []
    },
    {
      title: "COMP702: Prepare and submit",
      description: "Prepare final files and submit before the deadline.",
      source_type: "assignment",
      source_id: "file_sample",
      start_time: "2026-10-10T15:00:00Z",
      deadline: "2026-10-10T16:00:00Z",
      estimated_minutes: 60,
      priority: "urgent",
      status: "todo",
      evidence: []
    }
  ],
  events: [],
  reminders: [
    {
      title: "Reminder: COMP702: Prepare and submit",
      remind_at: "2026-10-09T16:00:00Z",
      channel: "in_app",
      task_title: "COMP702: Prepare and submit"
    }
  ],
  conflicts: [],
  assumptions: ["Generated default coursework timeline from assignment deadline."],
  selected_strategy: "deadline_safe",
  planning_candidates: [
    {
      strategy: "deadline_safe",
      task_count: 3,
      event_count: 0,
      conflict_count: 0,
      score: {
        conflict_penalty: 0,
        deadline_safety: 8,
        priority_alignment: 8,
        preference_alignment: 0,
        workload_balance: 8,
        evidence_alignment: 0,
        total: 24
      },
      assumptions: ["Candidate thought: maximize deadline buffer and start important work early."]
    }
  ],
  thought_trace: [
    {
      step: "select",
      strategy: "deadline_safe",
      rationale: "Selected deadline_safe because it had the highest total score.",
      score: {
        conflict_penalty: 0,
        deadline_safety: 8,
        priority_alignment: 8,
        preference_alignment: 0,
        workload_balance: 8,
        evidence_alignment: 0,
        total: 24
      }
    }
  ]
};

export const sampleNoticeActions: ActionItem[] = [
  {
    action_type: "assignment_deadline",
    title: "Submit COMP702 research report",
    description: "Upload final report and reference list through the university portal.",
    source_type: "notice",
    source_id: "notice_sample",
    deadline: "2026-10-10T16:00:00Z",
    estimated_minutes: 60,
    priority: "urgent",
    evidence: [
      {
        source_name: "Coursework Brief.pdf",
        page: 2,
        quote: "Submission deadline: 10 October 2026, 16:00.",
        start_char: 420,
        end_char: 466,
        confidence: 0.94
      }
    ]
  }
];

export const sampleResearchSources: ResearchSource[] = [
  {
    source_type: "web",
    title: "Evaluating RAG Systems in Education",
    url: "https://example.edu/rag-education",
    summary: "Overview of evidence quality, retrieval quality, and academic integrity risks.",
    authors: ["Sample Author"],
    published_at: "2026",
    evidence: [],
    metadata: { provider: "sample" }
  }
];

export const sampleIdeaVerification: IdeaVerificationResponse = {
  findings: [
    {
      idea: "Evaluate a student-facing RAG assistant for coursework planning.",
      status: "supported",
      reasons: ["Idea has at least one relevant research source.", "Check marking criteria before final selection."],
      supporting_sources: ["Evaluating RAG Systems in Education"]
    }
  ],
  recommended_ideas: ["Evaluate a student-facing RAG assistant for coursework planning."]
};

export const sampleEmail: EmailDraft = {
  recipient_type: "professor",
  subject: "Question About COMP702 Coursework Requirement",
  body:
    "Dear Professor [Name],\n\nI hope you are well. I am working through the COMP702 coursework brief and would like to confirm whether appendices count toward the 3000-word limit.\n\nThank you for your time.\n\nBest regards,\n[Your Name]",
  tone: "formal",
  missing_information: ["Professor name", "Sender name"],
  requires_user_approval: true
};

export const sampleTrace: TraceStep[] = [
  { name: "Router", detail: "primary_intent = assignment", status: "done" },
  { name: "Assignment Agent", detail: "Extracted deadline and word limit with evidence", status: "done" },
  { name: "Task Planner", detail: "Created tasks and reminder drafts", status: "done" },
  { name: "Email Agent", detail: "Prepared draft; send action requires approval", status: "done" }
];

export const sampleFitness: FitnessPlanOutput = {
  summary: "Generated a 2-week balanced fitness plan.",
  workout_days: [
    {
      day_of_week: "mon",
      focus: "Balanced fitness session",
      duration_minutes: 35,
      blocks: [
        {
          name: "Warm-up",
          duration_minutes: 7,
          intensity: "low",
          instructions: ["Easy walk", "Dynamic mobility"]
        },
        {
          name: "Balanced fitness session",
          duration_minutes: 22,
          intensity: "moderate",
          instructions: ["Bodyweight strength circuit", "Core stability", "Mobility finish"]
        },
        {
          name: "Cool-down",
          duration_minutes: 6,
          intensity: "low",
          instructions: ["Slow breathing", "Gentle stretching"]
        }
      ],
      safety_notes: ["Start easier than expected for the first week."]
    },
    {
      day_of_week: "sat",
      focus: "Gentle movement and stress relief",
      duration_minutes: 45,
      blocks: [
        {
          name: "Main block",
          duration_minutes: 35,
          intensity: "low",
          instructions: ["Easy walk", "Light mobility flow", "Breathing reset"]
        }
      ],
      safety_notes: ["Stop if pain, dizziness, or unusual symptoms occur."]
    }
  ],
  habit_tasks: [
    {
      title: "Prepare workout clothes and water",
      description: "Set up simple friction-reduction before the next planned workout.",
      source_type: "fitness",
      estimated_minutes: 10,
      priority: "medium",
      status: "todo",
      evidence: []
    }
  ],
  schedule_tasks: [
    {
      title: "Fitness session: Balanced fitness session",
      description: "mon workout, 35 minutes. Task Planner should place this on the next matching weekday.",
      source_type: "fitness",
      source_id: "local_user:mon:0",
      estimated_minutes: 35,
      priority: "medium",
      status: "todo",
      evidence: []
    }
  ],
  progression: [
    {
      week: 1,
      focus: "Balanced fitness session",
      progression_rule: "Use baseline volume and keep effort controlled.",
      deload_or_review: "Record energy, soreness, and skipped sessions."
    },
    {
      week: 2,
      focus: "Balanced fitness session",
      progression_rule: "Progress gradually based on completion rate and perceived effort.",
      deload_or_review: "Increase only one variable: duration, reps, sets, or pace."
    }
  ],
  memory_candidates: [
    {
      namespace: "fitness",
      content: "Prefers short moderate workouts during the week.",
      requires_confirmation: true,
      confirmed: false
    }
  ],
  memory_confirmation: null,
  missing_information: ["equipment"],
  risk_notes: ["This is general fitness planning support and is not medical advice."],
  assumptions: ["Plan is built from user-provided availability and preferences."],
  disclaimer: "This is general fitness planning support and is not medical advice."
};

export const sampleSocialContent: SocialContentOutput = {
  summary: "Generated 3 xiaohongshu copy draft(s).",
  drafts: [
    {
      platform: "xiaohongshu",
      variant: "balanced",
      title: "留学第一周如何整理任务｜留学生真实记录",
      body:
        "最近想记录一下：留学第一周如何整理任务。\n\n我的观察：\n- 列清单\n- 确认 deadline\n- 给自己留缓冲\n\n留学生活很多时候不是一步到位，而是不断把混乱整理成可执行的小动作。",
      hashtags: ["留学生活", "海外学习", "留学生日常", "经验分享"],
      call_to_action: "你也有类似经历的话，可以先收藏，之后慢慢对照。",
      platform_fit_notes: ["Use short paragraphs, concrete steps, and privacy-safe anecdotes."]
    }
  ],
  safety: {
    level: "ok",
    issues: [],
    redactions: []
  },
  platform_standard: {
    platform: "xiaohongshu",
    recommended_length: "标题 12-24 字，正文 200-600 字，分段短，适合收藏。",
    structure: ["钩子标题", "真实经历", "步骤/清单", "提醒和边界", "轻量互动"],
    tone_notes: ["具体、经验感强"],
    privacy_rules: ["不暴露学校精确宿舍、地址、学号、签证号"]
  },
  platform_notes: ["Keep paragraphs short, concrete, and experience-led."],
  image_generation_tool: {
    tool_name: "social.image_generation.draft",
    status: "designed_not_enabled",
    boundary: "Image generation is a separate approved tool and is not executed by the copywriting agent.",
    expected_inputs: ["approved_copy_draft_id", "platform", "visual_style_reference", "privacy_review_status"]
  },
  memory_candidates: [
    {
      namespace: "social_content",
      content: "Social content preference: platform xiaohongshu, tone warm, language zh.",
      requires_confirmation: true,
      confirmed: false
    }
  ],
  memory_confirmation: null,
  assumptions: ["Current agent generates copy only; image generation must use a separate approved tool."],
  disclaimer: "This is writing support. Review privacy, accuracy, and platform rules before posting."
};
