CREATE TABLE IF NOT EXISTS workflow_runs (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    conversation_id VARCHAR(64),
    trace_id VARCHAR(64) NOT NULL,
    request_id VARCHAR(255) NOT NULL,
    workflow_type VARCHAR(64) NOT NULL DEFAULT 'chat',
    status VARCHAR(32) NOT NULL DEFAULT 'created',
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    plan_json JSONB,
    final_response TEXT,
    error_code VARCHAR(128),
    error_message TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    cancel_requested_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_workflow_run_user_request UNIQUE (user_id, request_id),
    CONSTRAINT uq_workflow_run_trace UNIQUE (trace_id)
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_user_id ON workflow_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_conversation_id ON workflow_runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status);

CREATE TABLE IF NOT EXISTS workflow_steps (
    id VARCHAR(64) PRIMARY KEY,
    workflow_id VARCHAR(64) NOT NULL REFERENCES workflow_runs(id),
    step_key VARCHAR(128) NOT NULL,
    intent_name VARCHAR(128) NOT NULL,
    agent_intent VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    input_json JSONB,
    input_ref VARCHAR(255),
    result_summary TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TIMESTAMPTZ,
    lease_owner VARCHAR(255),
    lease_expires_at TIMESTAMPTZ,
    last_error_code VARCHAR(128),
    last_error_message TEXT,
    missing_information_json JSONB,
    queued_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_workflow_step_key UNIQUE (workflow_id, step_key)
);

CREATE INDEX IF NOT EXISTS idx_workflow_steps_workflow_id ON workflow_steps(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_agent_intent ON workflow_steps(agent_intent);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_status ON workflow_steps(status);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_available_at ON workflow_steps(available_at);
CREATE INDEX IF NOT EXISTS idx_workflow_steps_lease_expires_at ON workflow_steps(lease_expires_at);

CREATE TABLE IF NOT EXISTS workflow_step_dependencies (
    id VARCHAR(64) PRIMARY KEY,
    step_id VARCHAR(64) NOT NULL REFERENCES workflow_steps(id),
    depends_on_step_id VARCHAR(64) NOT NULL REFERENCES workflow_steps(id),
    dependency_type VARCHAR(32) NOT NULL DEFAULT 'success',
    condition_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_workflow_step_dependency UNIQUE (step_id, depends_on_step_id)
);

CREATE INDEX IF NOT EXISTS idx_workflow_step_dependencies_step_id ON workflow_step_dependencies(step_id);
CREATE INDEX IF NOT EXISTS idx_workflow_step_dependencies_depends_on ON workflow_step_dependencies(depends_on_step_id);

CREATE TABLE IF NOT EXISTS agent_artifacts (
    id VARCHAR(64) PRIMARY KEY,
    workflow_id VARCHAR(64) NOT NULL REFERENCES workflow_runs(id),
    step_id VARCHAR(64) NOT NULL REFERENCES workflow_steps(id),
    user_id VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    kind VARCHAR(128) NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    payload_json JSONB,
    storage_uri TEXT,
    checksum VARCHAR(128),
    size_bytes BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_artifacts_workflow_id ON agent_artifacts(workflow_id);
CREATE INDEX IF NOT EXISTS idx_agent_artifacts_step_id ON agent_artifacts(step_id);
CREATE INDEX IF NOT EXISTS idx_agent_artifacts_user_id ON agent_artifacts(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_artifacts_kind ON agent_artifacts(kind);
CREATE INDEX IF NOT EXISTS idx_agent_artifacts_checksum ON agent_artifacts(checksum);

CREATE TABLE IF NOT EXISTS message_inbox (
    consumer_name VARCHAR(128) NOT NULL,
    message_id VARCHAR(64) NOT NULL,
    workflow_id VARCHAR(64),
    step_id VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'processing',
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMPTZ,
    error TEXT,
    PRIMARY KEY (consumer_name, message_id)
);

CREATE INDEX IF NOT EXISTS idx_message_inbox_workflow_id ON message_inbox(workflow_id);
CREATE INDEX IF NOT EXISTS idx_message_inbox_step_id ON message_inbox(step_id);
CREATE INDEX IF NOT EXISTS idx_message_inbox_status ON message_inbox(status);

CREATE TABLE IF NOT EXISTS outbox_events (
    id VARCHAR(64) PRIMARY KEY,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id VARCHAR(64) NOT NULL,
    message_type VARCHAR(128) NOT NULL,
    routing_key VARCHAR(255) NOT NULL,
    payload_json JSONB NOT NULL,
    headers_json JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_outbox_events_status_available ON outbox_events(status, available_at);
CREATE INDEX IF NOT EXISTS idx_outbox_events_aggregate ON outbox_events(aggregate_type, aggregate_id);
CREATE INDEX IF NOT EXISTS idx_outbox_events_routing_key ON outbox_events(routing_key);

CREATE TABLE IF NOT EXISTS workflow_event_log (
    id BIGSERIAL PRIMARY KEY,
    workflow_id VARCHAR(64) NOT NULL REFERENCES workflow_runs(id),
    step_id VARCHAR(64) REFERENCES workflow_steps(id),
    event_type VARCHAR(128) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_workflow_event_log_workflow_id ON workflow_event_log(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_event_log_step_id ON workflow_event_log(step_id);
CREATE INDEX IF NOT EXISTS idx_workflow_event_log_type ON workflow_event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_workflow_event_log_created_at ON workflow_event_log(created_at);

ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS workflow_id VARCHAR(64) REFERENCES workflow_runs(id);
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS step_id VARCHAR(64) REFERENCES workflow_steps(id);
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 1;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_agent_runs_workflow_id ON agent_runs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_step_id ON agent_runs(step_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_idempotency_key ON agent_runs(idempotency_key);

CREATE UNIQUE INDEX IF NOT EXISTS uq_email_send_attempt_user_idempotency
ON email_send_attempts(user_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;
