# RabbitMQ migration fault-injection matrix

The default suite is deterministic and does not stop local services. Run `cd backend && pytest -q` first.

| Contract boundary | Automated evidence |
|---|---|
| Workflow state and Outbox share a PostgreSQL commit | `test_email_workflow_is_durable_and_idempotent` |
| Publisher confirm is lost | `test_outbox_recovers_when_publish_confirmation_is_lost` |
| Database/infrastructure becomes unavailable while consuming | `test_consumer_requeues_infrastructure_errors_but_rejects_permanent_payload_errors` |
| Two consumers receive the same completion event | `test_concurrent_completion_event_and_api_restart_are_idempotent` |
| Unsupported schema reaches a real DLQ | `test_unsupported_schema_is_rejected_to_real_dead_letter_queue` |
| Provider succeeds and audit persistence fails | `test_provider_success_followed_by_audit_failure_never_sends_twice` |
| API process restarts between creation and completion | `test_concurrent_completion_event_and_api_restart_are_idempotent` |
| Duplicate request/message idempotency | `test_concurrent_request_and_inbox_idempotency` |
| Expired worker lease | `test_expired_worker_lease_reaches_dlq_and_finalizes_workflow` |
| Conditional DAG and reminder-to-email closure | `test_conditioned_dependency_and_approved_reminder_delivery_close_the_loop` |
| Broker restart and publisher reconnection | `test_publisher_recovers_after_real_rabbitmq_restart` (explicit destructive opt-in) |

Real services:

```bash
docker compose -f docker-compose.rabbitmq.yml up -d --build
cd backend
RUN_WORKFLOW_INTEGRATION=1 RUN_RABBITMQ_INTEGRATION=1 pytest -q \
  tests/test_workflow_postgres_integration.py tests/test_rabbitmq_integration.py
```

To let the suite restart the Compose broker, add `RUN_RABBITMQ_RESTART_FAULT=1`. This flag is deliberately
separate because the test interrupts the shared local RabbitMQ service.

RabbitMQ restart drill (operator/CI): submit several async workflows, restart one RabbitMQ pod at a time,
wait for quorum health, and assert every workflow reaches a terminal state with one logical result. During the
drill, alert on ready/unacked depth, oldest message age, publisher-confirm latency, stale worker heartbeats and
DLQ growth. A three-node production cluster must retain quorum throughout; do not restart two nodes together.

Database outage drill: block application-to-PostgreSQL traffic for 30 seconds while workers hold deliveries,
then restore it. Consumers must `nack(requeue=True)` infrastructure failures, leases must recover abandoned
runs, and permanent validation errors alone must be rejected to the DLQ. Run this only in an isolated CI or
staging namespace.
