import os
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.messaging.connection import rabbitmq_manager
from app.messaging.consumer import RabbitMQConsumer
from app.messaging.publisher import RabbitMQPublisher
from app.messaging.serialization import deserialize_message
from app.schemas.messages import WorkflowPrepareCommand


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_RABBITMQ_INTEGRATION") != "1",
    reason="Set RUN_RABBITMQ_INTEGRATION=1 with RabbitMQ running",
)


@pytest.mark.asyncio
async def test_publisher_confirm_and_manual_ack_round_trip() -> None:
    await rabbitmq_manager.declare_topology()
    command = WorkflowPrepareCommand(
        workflow_id="integration-workflow",
        trace_id="integration-trace",
        input_ref="workflow-input:integration-workflow",
    )
    await RabbitMQPublisher().publish(routing_key="workflow.prepare", message=command)
    channel = await rabbitmq_manager.channel(publisher_confirms=False, on_return_raises=False)
    queue = await channel.get_queue("study.workflow.prepare.q", ensure=True)
    delivery = await queue.get(no_ack=False, timeout=5)
    assert delivery is not None
    restored = deserialize_message(delivery.body, WorkflowPrepareCommand)
    assert restored.message_id == command.message_id
    await delivery.ack()
    await channel.close()
    await rabbitmq_manager.close()


@pytest.mark.asyncio
async def test_unsupported_schema_is_rejected_to_real_dead_letter_queue() -> None:
    await rabbitmq_manager.declare_topology()
    message_id = str(uuid4())

    async def validate(message) -> None:
        deserialize_message(message.body, WorkflowPrepareCommand)

    consumer = RabbitMQConsumer("study.workflow.prepare.q", validate)
    await consumer.start()
    await RabbitMQPublisher().publish(
        routing_key="workflow.prepare",
        message={
            "schema_version": 999,
            "message_id": message_id,
            "message_type": "workflow.prepare",
            "workflow_id": "unsupported-version-workflow",
            "trace_id": "unsupported-version-trace",
            "input_ref": "workflow-input:unsupported-version-workflow",
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    channel = await rabbitmq_manager.channel(publisher_confirms=False, on_return_raises=False)
    queue = await channel.get_queue("study.dead.q", ensure=True)
    found = False
    for _ in range(20):
        delivery = await queue.get(no_ack=False, fail=False)
        if delivery is not None:
            if delivery.message_id == message_id:
                found = True
            await delivery.ack()
            if found:
                break
        await asyncio.sleep(0.1)
    await consumer.stop()
    await channel.close()
    await rabbitmq_manager.close()
    assert found


@pytest.mark.skipif(
    os.getenv("RUN_RABBITMQ_RESTART_FAULT") != "1",
    reason="Set RUN_RABBITMQ_RESTART_FAULT=1 to allow this test to restart the Compose broker",
)
@pytest.mark.asyncio
async def test_publisher_recovers_after_real_rabbitmq_restart() -> None:
    await rabbitmq_manager.close()
    project_root = Path(__file__).parents[2]
    process = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", "docker-compose.rabbitmq.yml", "restart", "rabbitmq",
        cwd=project_root,
    )
    assert await process.wait() == 0

    last_error = None
    for _ in range(30):
        try:
            await rabbitmq_manager.declare_topology()
            break
        except Exception as exc:
            last_error = exc
            await rabbitmq_manager.close()
            await asyncio.sleep(1)
    else:
        raise AssertionError(f"RabbitMQ did not recover after restart: {last_error}")

    command = WorkflowPrepareCommand(
        workflow_id="restart-workflow",
        trace_id="restart-trace",
        input_ref="workflow-input:restart-workflow",
    )
    await RabbitMQPublisher().publish(routing_key="workflow.prepare", message=command)
    channel = await rabbitmq_manager.channel(publisher_confirms=False, on_return_raises=False)
    queue = await channel.get_queue("study.workflow.prepare.q", ensure=True)
    delivery = await queue.get(no_ack=False, timeout=5)
    assert delivery is not None
    assert deserialize_message(delivery.body, WorkflowPrepareCommand).message_id == command.message_id
    await delivery.ack()
    await channel.close()
    await rabbitmq_manager.close()
