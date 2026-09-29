from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.memory.candidates import MemoryCandidateService
from app.memory.repository import LongTermMemoryRepository
from app.schemas.memory import (
    MemoryCandidateDecisionRequest,
    MemoryCandidateDecisionResponse,
    MemoryCandidatePersistRequest,
    MemoryCandidatePersistResponse,
    MemoryReviewResponse,
)

router = APIRouter()


@router.get("/review", response_model=MemoryReviewResponse)
async def review_memories(
    user_id: str,
    namespaces: list[str] | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> MemoryReviewResponse:
    return await MemoryCandidateService(LongTermMemoryRepository(session)).review(
        user_id=user_id,
        namespaces=namespaces,
    )


@router.post("/candidates", response_model=MemoryCandidatePersistResponse)
async def persist_memory_candidates(
    request: MemoryCandidatePersistRequest,
    session: AsyncSession = Depends(get_session),
) -> MemoryCandidatePersistResponse:
    result = await MemoryCandidateService(LongTermMemoryRepository(session)).persist_candidates(
        user_id=request.user_id,
        candidates=request.candidates,
        requested=request.requested,
        confirmed=request.confirmed,
        source_id=request.source_id,
    )
    await session.commit()
    return result


@router.post("/candidates/confirm", response_model=MemoryCandidateDecisionResponse)
async def confirm_memory_candidates(
    request: MemoryCandidateDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> MemoryCandidateDecisionResponse:
    result = await MemoryCandidateService(LongTermMemoryRepository(session)).confirm(
        user_id=request.user_id,
        memory_ids=request.memory_ids,
    )
    await session.commit()
    return result


@router.post("/candidates/reject", response_model=MemoryCandidateDecisionResponse)
async def reject_memory_candidates(
    request: MemoryCandidateDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> MemoryCandidateDecisionResponse:
    result = await MemoryCandidateService(LongTermMemoryRepository(session)).reject(
        user_id=request.user_id,
        memory_ids=request.memory_ids,
    )
    await session.commit()
    return result


@router.post("/delete", response_model=MemoryCandidateDecisionResponse)
async def delete_memories(
    request: MemoryCandidateDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> MemoryCandidateDecisionResponse:
    result = await MemoryCandidateService(LongTermMemoryRepository(session)).delete(
        user_id=request.user_id,
        memory_ids=request.memory_ids,
    )
    await session.commit()
    return result
