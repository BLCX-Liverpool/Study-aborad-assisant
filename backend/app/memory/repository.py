from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ConversationMessage, Memory, MemoryAccessLog
from app.rag.bm25 import InMemoryBM25Index
from app.schemas.chat import ChatTurn
from app.schemas.memory import LongTermMemoryItem
from app.memory.token_counter import TokenCounter

PENDING_MEMORY_TYPES = {"memory_candidate", "travel_preference_candidate"}
REJECTED_MEMORY_TYPES = {"rejected_memory_candidate"}


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_conversation(
        self,
        *,
        conversation_id: str,
        user_id: str,
        topic_summary: str | None = None,
    ) -> None:
        existing = await self.session.get(Conversation, conversation_id)
        if existing is not None:
            if topic_summary:
                existing.topic_summary = topic_summary
            return
        self.session.add(
            Conversation(
                id=conversation_id,
                user_id=user_id,
                topic_summary=topic_summary,
            )
        )

    async def append_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        message: ChatTurn,
        metadata: dict | None = None,
    ) -> None:
        self.session.add(
            ConversationMessage(
                conversation_id=conversation_id,
                user_id=user_id,
                role=message.role,
                content=message.content,
                token_count=TokenCounter().count_text(message.content),
                message_metadata_json=metadata,
            )
        )

    async def commit(self) -> None:
        await self.session.commit()


class LongTermMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        *,
        user_id: str,
        query: str,
        namespaces: list[str],
        top_k: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[LongTermMemoryItem]:
        if not namespaces:
            return []

        statement = select(Memory).where(
            Memory.user_id == user_id,
            Memory.namespace.in_(namespaces),
            Memory.memory_type.not_in(PENDING_MEMORY_TYPES | REJECTED_MEMORY_TYPES),
        )
        statement = statement.order_by(Memory.updated_at.desc()).limit(max(top_k * 12, 50))

        result = await self.session.execute(statement)
        memories = [memory for memory in result.scalars().all() if not _is_unconfirmed_or_rejected(memory)]
        if not memories:
            return []

        bm25 = InMemoryBM25Index([memory.content for memory in memories])
        bm25_scores = _normalize_scores(bm25.score(query))
        scored = []
        for index, memory in enumerate(memories):
            vector_score = _cosine_similarity(memory.embedding, query_embedding) if memory.embedding and query_embedding else 0.0
            lexical_score = bm25_scores[index] if index < len(bm25_scores) else 0.0
            substring_score = _substring_score(memory.content, query)
            score = 0.45 * lexical_score + 0.45 * vector_score + 0.10 * substring_score
            if score >= 0.08:
                scored.append(_to_memory_item(memory, score=score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]

    async def list_memories(
        self,
        *,
        user_id: str,
        namespaces: list[str] | None = None,
        include_candidates: bool = False,
        limit: int = 100,
    ) -> list[LongTermMemoryItem]:
        statement = select(Memory).where(Memory.user_id == user_id)
        if namespaces:
            statement = statement.where(Memory.namespace.in_(namespaces))
        if not include_candidates:
            statement = statement.where(Memory.memory_type.not_in(PENDING_MEMORY_TYPES | REJECTED_MEMORY_TYPES))
        statement = statement.order_by(Memory.updated_at.desc()).limit(limit)
        result = await self.session.execute(statement)
        return [_to_memory_item(memory) for memory in result.scalars().all()]

    async def list_memory_candidates(
        self,
        *,
        user_id: str,
        namespaces: list[str] | None = None,
        include_rejected: bool = False,
        limit: int = 100,
    ) -> list[LongTermMemoryItem]:
        candidate_types = set(PENDING_MEMORY_TYPES)
        if include_rejected:
            candidate_types |= REJECTED_MEMORY_TYPES
        statement = select(Memory).where(
            Memory.user_id == user_id,
            Memory.memory_type.in_(candidate_types),
        )
        if namespaces:
            statement = statement.where(Memory.namespace.in_(namespaces))
        statement = statement.order_by(Memory.updated_at.desc()).limit(limit)
        result = await self.session.execute(statement)
        return [_to_memory_item(memory) for memory in result.scalars().all()]

    async def add_memory(
        self,
        *,
        user_id: str,
        namespace: str,
        memory_type: str,
        content: str,
        source_type: str | None = None,
        source_id: str | None = None,
        confidence: float = 0.7,
        embedding: list[float] | None = None,
        access_policy: dict | None = None,
    ) -> str:
        memory = Memory(
            user_id=user_id,
            namespace=namespace,
            memory_type=memory_type,
            content=content,
            source_type=source_type,
            source_id=source_id,
            confidence=confidence,
            embedding=embedding,
            access_policy_json=access_policy,
        )
        self.session.add(memory)
        await self.session.flush()
        return memory.id

    async def add_memory_candidate(
        self,
        *,
        user_id: str,
        namespace: str,
        content: str,
        source_type: str | None = None,
        source_id: str | None = None,
        confidence: float = 0.7,
        embedding: list[float] | None = None,
        access_policy: dict | None = None,
        memory_type: str = "memory_candidate",
    ) -> str:
        policy = {
            "requires_user_confirmation": True,
            "confirmed": False,
            "rejected": False,
            "reason": "Memory candidate must be explicitly confirmed before long-term use.",
        }
        if access_policy:
            policy.update(access_policy)
        return await self.add_memory(
            user_id=user_id,
            namespace=namespace,
            memory_type=memory_type,
            content=content,
            source_type=source_type,
            source_id=source_id,
            confidence=confidence,
            embedding=embedding,
            access_policy=policy,
        )

    async def confirm_memory_candidates(self, *, user_id: str, memory_ids: list[str]) -> list[str]:
        if not memory_ids:
            return []
        result = await self.session.execute(
            select(Memory).where(
                Memory.user_id == user_id,
                Memory.id.in_(memory_ids),
                Memory.memory_type.in_(PENDING_MEMORY_TYPES),
            )
        )
        confirmed_ids = []
        for memory in result.scalars().all():
            memory.memory_type = "user_preference"
            policy = dict(memory.access_policy_json or {})
            policy["requires_user_confirmation"] = False
            policy["confirmed"] = True
            policy["rejected"] = False
            policy["reason"] = "Confirmed by user through memory confirmation flow."
            memory.access_policy_json = policy
            confirmed_ids.append(memory.id)
        await self.session.flush()
        return confirmed_ids

    async def reject_memory_candidates(self, *, user_id: str, memory_ids: list[str]) -> list[str]:
        if not memory_ids:
            return []
        result = await self.session.execute(
            select(Memory).where(
                Memory.user_id == user_id,
                Memory.id.in_(memory_ids),
                Memory.memory_type.in_(PENDING_MEMORY_TYPES),
            )
        )
        rejected_ids = []
        for memory in result.scalars().all():
            memory.memory_type = "rejected_memory_candidate"
            policy = dict(memory.access_policy_json or {})
            policy["requires_user_confirmation"] = False
            policy["confirmed"] = False
            policy["rejected"] = True
            policy["reason"] = "Rejected by user through memory review flow."
            memory.access_policy_json = policy
            rejected_ids.append(memory.id)
        await self.session.flush()
        return rejected_ids

    async def delete_memories(self, *, user_id: str, memory_ids: list[str]) -> list[str]:
        if not memory_ids:
            return []
        existing_result = await self.session.execute(
            select(Memory.id).where(Memory.user_id == user_id, Memory.id.in_(memory_ids))
        )
        existing_ids = list(existing_result.scalars().all())
        if not existing_ids:
            return []
        await self.session.execute(delete(MemoryAccessLog).where(MemoryAccessLog.memory_id.in_(existing_ids)))
        await self.session.execute(delete(Memory).where(Memory.user_id == user_id, Memory.id.in_(existing_ids)))
        await self.session.flush()
        return existing_ids

    async def record_access(
        self,
        *,
        agent_run_id: str,
        memory_ids: list[str],
        access_type: str,
        reason: str | None = None,
    ) -> int:
        count = 0
        for memory_id in memory_ids:
            self.session.add(
                MemoryAccessLog(
                    agent_run_id=agent_run_id,
                    memory_id=memory_id,
                    access_type=access_type,
                    reason=reason,
                )
            )
            count += 1
        await self.session.flush()
        return count


def _score_memory(
    content: str,
    query: str,
    memory_embedding: list[float] | None = None,
    query_embedding: list[float] | None = None,
) -> float:
    content_terms = set(content.lower().split())
    query_terms = set(query.lower().split())
    lexical = len(content_terms & query_terms) / len(query_terms) if query_terms else 0.0
    if memory_embedding and query_embedding:
        return 0.55 * lexical + 0.45 * _cosine_similarity(memory_embedding, query_embedding)
    return lexical


def _normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return []
    max_score = max(scores)
    if max_score <= 0:
        return [0.0 for _ in scores]
    return [score / max_score for score in scores]


def _substring_score(content: str, query: str) -> float:
    content_lower = content.lower()
    terms = [term.lower() for term in query.replace("，", " ").replace("。", " ").split() if len(term) >= 2]
    if not terms:
        return 0.0
    matches = sum(1 for term in terms if term in content_lower)
    return matches / len(terms)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _is_unconfirmed_or_rejected(memory: Memory) -> bool:
    policy = dict(memory.access_policy_json or {})
    return (
        memory.memory_type in PENDING_MEMORY_TYPES
        or memory.memory_type in REJECTED_MEMORY_TYPES
        or policy.get("confirmed") is False
        or policy.get("rejected") is True
    )


def _to_memory_item(memory: Memory, *, score: float = 0.0) -> LongTermMemoryItem:
    return LongTermMemoryItem(
        id=memory.id,
        namespace=memory.namespace,
        memory_type=memory.memory_type,
        content=memory.content,
        score=score,
        source_type=memory.source_type,
        source_id=memory.source_id,
        confidence=memory.confidence,
        access_policy=memory.access_policy_json,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )
