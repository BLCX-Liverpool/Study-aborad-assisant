import asyncio

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.workflows.repository import WorkflowRepository


class StepLeaseHeartbeat:
    def __init__(self, *, step_id: str, worker_id: str) -> None:
        self.step_id = step_id
        self.worker_id = worker_id
        self.lease_seconds = get_settings().workflow_lease_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        interval = max(5.0, self.lease_seconds / 3)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break
            except TimeoutError:
                pass
            async with get_session_factory()() as session:
                changed = await WorkflowRepository(session).heartbeat_step(
                    self.step_id,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
                await session.commit()
                if not changed:
                    break
