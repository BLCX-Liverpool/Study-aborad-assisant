import os

import pytest

from app.messaging.connection import rabbitmq_manager
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
