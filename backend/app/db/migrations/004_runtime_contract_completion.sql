ALTER TABLE workflow_steps ALTER COLUMN max_attempts SET DEFAULT 4;
UPDATE workflow_steps
SET max_attempts = 4
WHERE max_attempts = 3 AND attempt_count = 0;

ALTER TABLE reminders ADD COLUMN IF NOT EXISTS recipient_email VARCHAR(255);
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS delivery_approved BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ;
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);
CREATE INDEX IF NOT EXISTS idx_reminders_idempotency_key ON reminders(idempotency_key);

ALTER TABLE message_inbox ADD COLUMN IF NOT EXISTS exchange_name VARCHAR(255);
ALTER TABLE message_inbox ADD COLUMN IF NOT EXISTS routing_key VARCHAR(255);
ALTER TABLE message_inbox ADD COLUMN IF NOT EXISTS message_type VARCHAR(128);
ALTER TABLE message_inbox ADD COLUMN IF NOT EXISTS payload_json JSONB;
ALTER TABLE message_inbox ADD COLUMN IF NOT EXISTS headers_json JSONB;
ALTER TABLE message_inbox ADD COLUMN IF NOT EXISTS causation_id VARCHAR(64);

ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS publish_latency_ms DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id VARCHAR(255) PRIMARY KEY,
    queue_names_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json JSONB
);
CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_last_seen_at ON worker_heartbeats(last_seen_at);
