from collections.abc import Iterable
from typing import Any

from app.memory.policy import retention_policy_for
from app.memory.repository import LongTermMemoryRepository
from app.rag.embeddings import EmbeddingService
from app.schemas.memory import (
    MemoryCandidateDecisionResponse,
    MemoryCandidateInput,
    MemoryCandidatePersistResponse,
    MemoryReviewResponse,
)


class MemoryCandidateService:
    def __init__(
        self,
        repository: LongTermMemoryRepository,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.repository = repository
        self.embedding_service = embedding_service

    async def persist_candidates(
        self,
        *,
        user_id: str,
        candidates: Iterable[MemoryCandidateInput | Any],
        requested: bool,
        confirmed: bool = False,
        source_id: str | None = None,
    ) -> MemoryCandidatePersistResponse:
        normalized = [_normalize_candidate(candidate) for candidate in candidates]
        if not requested:
            return MemoryCandidatePersistResponse(
                status="not_requested",
                candidate_count=len(normalized),
            )
        if not normalized:
            return MemoryCandidatePersistResponse(
                status="not_requested",
                candidate_count=0,
                assumptions=["Agent did not produce memory candidates for this request."],
            )

        pending_ids: list[str] = []
        confirmed_ids: list[str] = []
        skipped: list[str] = []
        try:
            for candidate in normalized:
                user_confirmed = confirmed or candidate.confirmed
                policy = retention_policy_for(candidate.content, user_confirmed=user_confirmed)
                if not policy.retain and policy.sensitivity != "medium":
                    skipped.append(candidate.content)
                    continue
                access_policy = {
                    "sensitivity": policy.sensitivity,
                    "requires_user_confirmation": policy.requires_user_confirmation,
                    "confirmed": user_confirmed and not policy.requires_user_confirmation,
                    "rejected": False,
                    "expires_at": policy.expires_at.isoformat() if policy.expires_at else None,
                    "reason": policy.reason,
                    "agent_name": candidate.agent_name,
                }
                embedding = await self._embed_optional(candidate.content)
                if user_confirmed and not policy.requires_user_confirmation:
                    memory_id = await self.repository.add_memory(
                        user_id=user_id,
                        namespace=str(candidate.namespace),
                        memory_type="user_preference",
                        content=candidate.content,
                        source_type=candidate.source_type,
                        source_id=source_id or candidate.source_id,
                        confidence=candidate.confidence,
                        embedding=embedding,
                        access_policy=access_policy,
                    )
                    confirmed_ids.append(memory_id)
                    continue
                memory_id = await self.repository.add_memory_candidate(
                    user_id=user_id,
                    namespace=str(candidate.namespace),
                    content=candidate.content,
                    source_type=candidate.source_type,
                    source_id=source_id or candidate.source_id,
                    confidence=candidate.confidence,
                    embedding=embedding,
                    access_policy=access_policy,
                )
                pending_ids.append(memory_id)
        except Exception as exc:
            return MemoryCandidatePersistResponse(
                status="failed",
                candidate_count=len(normalized),
                pending_memory_ids=pending_ids,
                confirmed_memory_ids=confirmed_ids,
                skipped=skipped,
                error=f"{type(exc).__name__}: {exc}",
            )

        if confirmed_ids and not pending_ids:
            status = "confirmed"
        elif pending_ids:
            status = "pending_confirmation"
        else:
            status = "skipped"
        return MemoryCandidatePersistResponse(
            status=status,
            candidate_count=len(normalized),
            pending_memory_ids=pending_ids,
            confirmed_memory_ids=confirmed_ids,
            skipped=skipped,
            assumptions=[
                "Pending memory candidates are excluded from long-term retrieval until explicitly confirmed."
                if pending_ids
                else "Confirmed memory candidates are available to their memory namespaces."
                if confirmed_ids
                else "Memory candidates were skipped by sensitivity or retention policy."
            ],
        )

    async def review(self, *, user_id: str, namespaces: list[str] | None = None) -> MemoryReviewResponse:
        memories = await self.repository.list_memories(user_id=user_id, namespaces=namespaces)
        candidates = await self.repository.list_memory_candidates(user_id=user_id, namespaces=namespaces)
        return MemoryReviewResponse(user_id=user_id, memories=memories, candidates=candidates)

    async def confirm(self, *, user_id: str, memory_ids: list[str]) -> MemoryCandidateDecisionResponse:
        try:
            confirmed_ids = await self.repository.confirm_memory_candidates(user_id=user_id, memory_ids=memory_ids)
        except Exception as exc:
            return MemoryCandidateDecisionResponse(status="failed", error=f"{type(exc).__name__}: {exc}")
        return MemoryCandidateDecisionResponse(
            status="confirmed" if confirmed_ids else "pending_confirmation",
            memory_ids=confirmed_ids,
            assumptions=["Confirmed pending memory candidates." if confirmed_ids else "No matching pending memory candidates were found."],
        )

    async def reject(self, *, user_id: str, memory_ids: list[str]) -> MemoryCandidateDecisionResponse:
        try:
            rejected_ids = await self.repository.reject_memory_candidates(user_id=user_id, memory_ids=memory_ids)
        except Exception as exc:
            return MemoryCandidateDecisionResponse(status="failed", error=f"{type(exc).__name__}: {exc}")
        return MemoryCandidateDecisionResponse(
            status="rejected" if rejected_ids else "pending_confirmation",
            memory_ids=rejected_ids,
            assumptions=["Rejected pending memory candidates." if rejected_ids else "No matching pending memory candidates were found."],
        )

    async def delete(self, *, user_id: str, memory_ids: list[str]) -> MemoryCandidateDecisionResponse:
        try:
            deleted_ids = await self.repository.delete_memories(user_id=user_id, memory_ids=memory_ids)
        except Exception as exc:
            return MemoryCandidateDecisionResponse(status="failed", error=f"{type(exc).__name__}: {exc}")
        return MemoryCandidateDecisionResponse(
            status="deleted" if deleted_ids else "skipped",
            memory_ids=deleted_ids,
            assumptions=["Deleted selected memories." if deleted_ids else "No matching memories were found."],
        )

    async def _embed_optional(self, text: str) -> list[float] | None:
        if self.embedding_service is None:
            return None
        try:
            embeddings = await self.embedding_service.embed_texts([text])
        except Exception:
            return None
        return embeddings[0] if embeddings else None


def _normalize_candidate(candidate: MemoryCandidateInput | Any) -> MemoryCandidateInput:
    if isinstance(candidate, MemoryCandidateInput):
        return candidate
    if hasattr(candidate, "model_dump"):
        return MemoryCandidateInput.model_validate(candidate.model_dump())
    if isinstance(candidate, dict):
        return MemoryCandidateInput.model_validate(candidate)
    return MemoryCandidateInput.model_validate(
        {
            "namespace": getattr(candidate, "namespace"),
            "content": getattr(candidate, "content"),
            "source_type": getattr(candidate, "source_type", None),
            "source_id": getattr(candidate, "source_id", None),
            "confidence": getattr(candidate, "confidence", 0.7),
            "requires_confirmation": getattr(candidate, "requires_confirmation", True),
            "confirmed": getattr(candidate, "confirmed", False),
            "agent_name": getattr(candidate, "agent_name", None),
        }
    )
