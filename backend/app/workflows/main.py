import asyncio
import signal

from app.messaging.connection import rabbitmq_manager
from app.messaging.consumer import RabbitMQConsumer
from app.workflows.runtime import WorkflowEventRuntime, WorkflowPrepareRuntime
from app.messaging.dead_letter import DeadLetterRuntime
from app.core.config import get_settings


async def run() -> None:
    if get_settings().rabbitmq_declare_topology:
        await rabbitmq_manager.declare_topology()
    prepare_runtime = WorkflowPrepareRuntime()
    event_runtime = WorkflowEventRuntime()
    dead_letter_runtime = DeadLetterRuntime()
    consumers = [
        RabbitMQConsumer(prepare_runtime.consumer_name, prepare_runtime.handle_message),
        RabbitMQConsumer(event_runtime.consumer_name, event_runtime.handle_message),
        RabbitMQConsumer(dead_letter_runtime.consumer_name, dead_letter_runtime.handle_message),
    ]
    for consumer in consumers:
        await consumer.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    for consumer in consumers:
        await consumer.stop()
    await rabbitmq_manager.close()


if __name__ == "__main__":
    asyncio.run(run())
