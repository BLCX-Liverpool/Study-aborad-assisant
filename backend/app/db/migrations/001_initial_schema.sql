CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255),
    display_name VARCHAR(255),
    home_country VARCHAR(128),
    study_country VARCHAR(128),
    timezone VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS conversations (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    title VARCHAR(512),
    topic_summary TEXT,
    active_entities_json JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id VARCHAR(64) PRIMARY KEY,
    conversation_id VARCHAR(64) NOT NULL REFERENCES conversations(id),
    user_id VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    message_metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_id ON conversation_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_user_id ON conversation_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_created_at ON conversation_messages(created_at);

CREATE TABLE IF NOT EXISTS files (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    conversation_id VARCHAR(64),
    filename VARCHAR(512) NOT NULL,
    mime_type VARCHAR(255),
    storage_path TEXT NOT NULL,
    source_type VARCHAR(128) NOT NULL DEFAULT 'uploaded_document',
    checksum VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_files_user_id ON files(user_id);
CREATE INDEX IF NOT EXISTS idx_files_conversation_id ON files(conversation_id);
CREATE INDEX IF NOT EXISTS idx_files_checksum ON files(checksum);

CREATE TABLE IF NOT EXISTS document_chunks (
    id VARCHAR(64) PRIMARY KEY,
    file_id VARCHAR(64) NOT NULL REFERENCES files(id),
    user_id VARCHAR(64) NOT NULL,
    chunk_index INTEGER NOT NULL,
    page INTEGER,
    slide INTEGER,
    section VARCHAR(512),
    section_path JSONB,
    heading_level INTEGER,
    content_type VARCHAR(64),
    content TEXT NOT NULL,
    token_count INTEGER,
    bbox_json JSONB,
    parse_strategy VARCHAR(64),
    text_quality_score DOUBLE PRECISION,
    image_area_ratio DOUBLE PRECISION,
    source_metadata_json JSONB,
    embedding VECTOR,
    search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED,
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_file_id ON document_chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_user_id ON document_chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_search_vector ON document_chunks USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS memories (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    namespace VARCHAR(64) NOT NULL,
    memory_type VARCHAR(64) NOT NULL,
    content TEXT NOT NULL,
    source_type VARCHAR(128),
    source_id VARCHAR(64),
    confidence DOUBLE PRECISION,
    access_policy_json JSONB,
    embedding VECTOR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace);

CREATE TABLE IF NOT EXISTS tasks (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    title VARCHAR(512) NOT NULL,
    description TEXT,
    source_type VARCHAR(128),
    source_id VARCHAR(64),
    start_time TIMESTAMPTZ,
    deadline TIMESTAMPTZ,
    estimated_minutes INTEGER,
    priority VARCHAR(32) NOT NULL DEFAULT 'medium',
    status VARCHAR(32) NOT NULL DEFAULT 'todo',
    created_by_agent VARCHAR(128),
    evidence_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_deadline ON tasks(deadline);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS events (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    title VARCHAR(512) NOT NULL,
    description TEXT,
    location VARCHAR(512),
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    source_type VARCHAR(128),
    source_id VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'scheduled',
    evidence_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_user_id ON events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_start_time ON events(start_time);

CREATE TABLE IF NOT EXISTS reminders (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    task_id VARCHAR(64) REFERENCES tasks(id),
    event_id VARCHAR(64) REFERENCES events(id),
    remind_at TIMESTAMPTZ NOT NULL,
    channel VARCHAR(64) NOT NULL DEFAULT 'in_app',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reminders_user_id ON reminders(user_id);
CREATE INDEX IF NOT EXISTS idx_reminders_task_id ON reminders(task_id);
CREATE INDEX IF NOT EXISTS idx_reminders_event_id ON reminders(event_id);
CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at);

CREATE TABLE IF NOT EXISTS email_send_attempts (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    to_email VARCHAR(255) NOT NULL,
    from_email VARCHAR(255),
    subject VARCHAR(512) NOT NULL,
    body TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'requires_approval',
    approved BOOLEAN NOT NULL DEFAULT FALSE,
    source_type VARCHAR(128),
    source_id VARCHAR(64),
    idempotency_key VARCHAR(128),
    provider_message_id VARCHAR(255),
    sent_at TIMESTAMPTZ,
    error TEXT,
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_email_send_attempts_user_id ON email_send_attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_email_send_attempts_provider ON email_send_attempts(provider);
CREATE INDEX IF NOT EXISTS idx_email_send_attempts_status ON email_send_attempts(status);
CREATE INDEX IF NOT EXISTS idx_email_send_attempts_idempotency_key ON email_send_attempts(idempotency_key);

CREATE TABLE IF NOT EXISTS agent_runs (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    conversation_id VARCHAR(64),
    trace_id VARCHAR(64) NOT NULL,
    agent_name VARCHAR(128) NOT NULL,
    input_json JSONB,
    output_json JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_id ON agent_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_id ON agent_runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_trace_id ON agent_runs(trace_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_name ON agent_runs(agent_name);

CREATE TABLE IF NOT EXISTS router_observations (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    conversation_id VARCHAR(64),
    trace_id VARCHAR(64) NOT NULL,
    message TEXT NOT NULL,
    primary_intent VARCHAR(128) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    structured_intents_json JSONB,
    fusion_metadata_json JSONB,
    clarification_questions_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_router_observations_user_id ON router_observations(user_id);
CREATE INDEX IF NOT EXISTS idx_router_observations_conversation_id ON router_observations(conversation_id);
CREATE INDEX IF NOT EXISTS idx_router_observations_trace_id ON router_observations(trace_id);
CREATE INDEX IF NOT EXISTS idx_router_observations_primary_intent ON router_observations(primary_intent);

CREATE TABLE IF NOT EXISTS trace_spans (
    id VARCHAR(64) PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    parent_span_id VARCHAR(64),
    user_id VARCHAR(64),
    conversation_id VARCHAR(64),
    agent_run_id VARCHAR(64) REFERENCES agent_runs(id),
    span_name VARCHAR(128) NOT NULL,
    span_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'completed',
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    duration_ms DOUBLE PRECISION NOT NULL,
    input_json JSONB,
    output_json JSONB,
    error TEXT,
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trace_spans_trace_id ON trace_spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_spans_parent_span_id ON trace_spans(parent_span_id);
CREATE INDEX IF NOT EXISTS idx_trace_spans_user_id ON trace_spans(user_id);
CREATE INDEX IF NOT EXISTS idx_trace_spans_conversation_id ON trace_spans(conversation_id);
CREATE INDEX IF NOT EXISTS idx_trace_spans_agent_run_id ON trace_spans(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_trace_spans_span_name ON trace_spans(span_name);
CREATE INDEX IF NOT EXISTS idx_trace_spans_span_type ON trace_spans(span_type);
CREATE INDEX IF NOT EXISTS idx_trace_spans_status ON trace_spans(status);

CREATE TABLE IF NOT EXISTS tool_runs (
    id VARCHAR(64) PRIMARY KEY,
    agent_run_id VARCHAR(64) NOT NULL REFERENCES agent_runs(id),
    tool_name VARCHAR(128) NOT NULL,
    permission_level VARCHAR(64) NOT NULL,
    input_json JSONB,
    output_json JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tool_runs_agent_run_id ON tool_runs(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_tool_runs_tool_name ON tool_runs(tool_name);

CREATE TABLE IF NOT EXISTS memory_access_logs (
    id VARCHAR(64) PRIMARY KEY,
    agent_run_id VARCHAR(64) NOT NULL REFERENCES agent_runs(id),
    memory_id VARCHAR(64) NOT NULL REFERENCES memories(id),
    access_type VARCHAR(64) NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_access_logs_agent_run_id ON memory_access_logs(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_memory_access_logs_memory_id ON memory_access_logs(memory_id);

CREATE TABLE IF NOT EXISTS rag_retrieval_logs (
    id VARCHAR(64) PRIMARY KEY,
    agent_run_id VARCHAR(64) REFERENCES agent_runs(id),
    query TEXT NOT NULL,
    retrieval_type VARCHAR(64) NOT NULL,
    results_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_retrieval_logs_agent_run_id ON rag_retrieval_logs(agent_run_id);

CREATE TABLE IF NOT EXISTS permission_requests (
    id VARCHAR(64) PRIMARY KEY,
    agent_run_id VARCHAR(64) REFERENCES agent_runs(id),
    permission_level VARCHAR(64) NOT NULL,
    action_name VARCHAR(128) NOT NULL,
    request_json JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_permission_requests_agent_run_id ON permission_requests(agent_run_id);

CREATE TABLE IF NOT EXISTS verifier_results (
    id VARCHAR(64) PRIMARY KEY,
    agent_run_id VARCHAR(64) REFERENCES agent_runs(id),
    verifier_name VARCHAR(128) NOT NULL,
    status VARCHAR(64) NOT NULL,
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_verifier_results_agent_run_id ON verifier_results(agent_run_id);
