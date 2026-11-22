import argparse
import asyncio
from datetime import UTC, datetime
import os
import signal
import socket
from uuid import uuid4

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.db.models import WorkerHeartbeat

from app.messaging.connection import rabbitmq_manager
from app.messaging.consumer import RabbitMQConsumer
from app.workers.runtime import AgentWorkerRuntime


async def run(queue_names: list[str]) -> None:
    if get_settings().rabbitmq_declare_topology:
        await rabbitmq_manager.declare_topology()
    consumers = []
    for queue_name in queue_names:
        runtime = AgentWorkerRuntime(consumer_name=queue_name)
        consumer = RabbitMQConsumer(queue_name, runtime.handle_message)
        await consumer.start()
        consumers.append(consumer)
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(_worker_heartbeat(worker_id, queue_names, heartbeat_stop))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    heartbeat_stop.set()
    await heartbeat_task
    for consumer in consumers:
        await consumer.stop()
    await rabbitmq_manager.close()


async def _worker_heartbeat(worker_id: str, queue_names: list[str], stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with get_session_factory()() as session:
                record = await session.get(WorkerHeartbeat, worker_id)
                if record is None:
                    record = WorkerHeartbeat(worker_id=worker_id, queue_names_json=queue_names)
                    session.add(record)
                record.last_seen_at = datetime.now(UTC)
                await session.commit()
        except Exception:
            # Worker consumption must survive a temporary observability write failure.
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            continue


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an asynchronous agent worker")
    parser.add_argument("--queue", required=True, action="append")
    args = parser.parse_args()
    asyncio.run(run(args.queue))


if __name__ == "__main__":
    main()
