from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.redis import get_redis
from app.core.config import get_settings
from app.messaging.connection import rabbitmq_manager

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/health/readiness")
async def readiness_check(session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(text("SELECT 1"))
    redis_ok = bool(await get_redis().ping())
    rabbitmq_status = "disabled"
    rabbitmq_ok = True
    if get_settings().rabbitmq_workflow_enabled:
        try:
            connection = await rabbitmq_manager.connection()
            rabbitmq_ok = not connection.is_closed
        except Exception:
            rabbitmq_ok = False
        rabbitmq_status = "ready" if rabbitmq_ok else "unavailable"
    return {
        "status": "ready" if redis_ok and rabbitmq_ok else "degraded",
        "database": "ready",
        "redis": "ready" if redis_ok else "unavailable",
        "rabbitmq": rabbitmq_status,
        "timestamp": datetime.now(UTC).isoformat(),
    }

