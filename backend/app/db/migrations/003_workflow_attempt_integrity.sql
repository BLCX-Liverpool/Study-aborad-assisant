CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_run_workflow_step_attempt
ON agent_runs(workflow_id, step_id, attempt)
WHERE workflow_id IS NOT NULL AND step_id IS NOT NULL;
