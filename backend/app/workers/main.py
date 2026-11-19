import argparse
import asyncio
import signal

from app.messaging.connection import rabbitmq_manager
from app.messaging.consumer import RabbitMQConsumer
from app.workers.runtime import AgentWorkerRuntime


async def run(queue_names: list[str]) -> None:
    await rabbitmq_manager.declare_topology()
    consumers = []
    for queue_name in queue_names:
        runtime = AgentWorkerRuntime(consumer_name=queue_name)
        consumer = RabbitMQConsumer(queue_name, runtime.handle_message)
        await consumer.start()
        consumers.append(consumer)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    for consumer in consumers:
        await consumer.stop()
    await rabbitmq_manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an asynchronous agent worker")
    parser.add_argument("--queue", required=True, action="append")
    args = parser.parse_args()
    asyncio.run(run(args.queue))


if __name__ == "__main__":
    main()
