import asyncio
import signal

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.messaging.connection import rabbitmq_manager
from app.outbox.publisher import OutboxPublisher
from app.outbox.repository import OutboxRepository


async def run() -> None:
    if get_settings().rabbitmq_declare_topology:
        await rabbitmq_manager.declare_topology()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    settings = get_settings()
    while not stop.is_set():
        async with get_session_factory()() as session:
            repository = OutboxRepository(session)
            await repository.recover_stale_claims()
            count = await OutboxPublisher(repository).publish_once()
        if count == 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.5)
            except TimeoutError:
                pass
    await rabbitmq_manager.close()


if __name__ == "__main__":
    asyncio.run(run())
