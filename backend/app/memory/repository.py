from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ConversationMessage, Memory
from app.schemas.chat import ChatTurn
from app.schemas.memory import LongTermMemoryItem
from app.memory.token_counter import TokenCounter


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

        terms = [term for term in query.replace("，", " ").replace("。", " ").split() if len(term) >= 2]
        statement = select(Memory).where(
            Memory.user_id == user_id,
            Memory.namespace.in_(namespaces),
            Memory.memory_type != "travel_preference_candidate",
        )
        if terms:
            statement = statement.where(or_(*[Memory.content.ilike(f"%{term}%") for term in terms[:8]]))
        statement = statement.limit(top_k * 3)

        result = await self.session.execute(statement)
        memories = list(result.scalars().all())
        scored = [
            LongTermMemoryItem(
                id=memory.id,
                namespace=memory.namespace,
                memory_type=memory.memory_type,
                content=memory.content,
                score=_score_memory(memory.content, query, memory.embedding, query_embedding),
                source_type=memory.source_type,
                source_id=memory.source_id,
                confidence=memory.confidence,
            )
            for memory in memories
        ]
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]

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
    ) -> str:
        policy = {
            "requires_user_confirmation": True,
            "confirmed": False,
            "reason": "Travel preference candidate must be explicitly confirmed before long-term use.",
        }
        if access_policy:
            policy.update(access_policy)
        return await self.add_memory(
            user_id=user_id,
            namespace=namespace,
            memory_type="travel_preference_candidate",
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
                Memory.memory_type == "travel_preference_candidate",
            )
        )
        confirmed_ids = []
        for memory in result.scalars().all():
            memory.memory_type = "user_preference"
            policy = dict(memory.access_policy_json or {})
            policy["requires_user_confirmation"] = False
            policy["confirmed"] = True
            policy["reason"] = "Confirmed by user through Travel memory confirmation flow."
            memory.access_policy_json = policy
            confirmed_ids.append(memory.id)
        await self.session.flush()
        return confirmed_ids


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


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
