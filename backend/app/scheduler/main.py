import asyncio
import signal

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.scheduler.reminder_scheduler import ReminderScheduler
from app.scheduler.retry_scheduler import RetryScheduler
from app.scheduler.stale_run_recovery import StaleRunRecovery


async def run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    interval = get_settings().workflow_scheduler_poll_seconds
    while not stop.is_set():
        async with get_session_factory()() as session:
            await StaleRunRecovery(session).recover()
            await RetryScheduler(session).dispatch_due()
            await ReminderScheduler(session).enqueue_due()
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(run())
