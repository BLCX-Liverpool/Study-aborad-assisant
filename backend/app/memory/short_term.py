import json
from collections import defaultdict
from dataclasses import dataclass, field

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.memory.token_counter import TokenCounter
from app.schemas.chat import ChatTurn


@dataclass
class ShortTermMemoryConfig:
    max_messages: int = 20
    compression_threshold_ratio: float = 0.7
    retained_recent_messages: int = 6


class InMemoryShortTermMemoryStore:
    def __init__(self, config: ShortTermMemoryConfig | None = None) -> None:
        self.config = config or ShortTermMemoryConfig()
        self._messages: dict[str, list[ChatTurn]] = defaultdict(list)

    async def load_recent(self, conversation_id: str, limit: int = 10) -> list[ChatTurn]:
        return self._messages[conversation_id][-limit:]

    async def load_all(self, conversation_id: str) -> list[ChatTurn]:
        return list(self._messages[conversation_id])

    async def append(self, conversation_id: str, message: ChatTurn) -> None:
        self._messages[conversation_id].append(message)

    async def replace_all(self, conversation_id: str, messages: list[ChatTurn]) -> None:
        self._messages[conversation_id] = list(messages)


class RedisShortTermMemoryStore:
    def __init__(
        self,
        redis: Redis,
        fallback: InMemoryShortTermMemoryStore | None = None,
        config: ShortTermMemoryConfig | None = None,
    ) -> None:
        self.redis = redis
        self.config = config or ShortTermMemoryConfig()
        self.fallback = fallback or InMemoryShortTermMemoryStore(self.config)

    async def load_recent(self, conversation_id: str, limit: int = 10) -> list[ChatTurn]:
        key = _key(conversation_id)
        try:
            values = await self.redis.lrange(key, -limit, -1)
        except RedisError:
            return await self.fallback.load_recent(conversation_id, limit)
        return [ChatTurn.model_validate_json(value) for value in values]

    async def load_all(self, conversation_id: str) -> list[ChatTurn]:
        key = _key(conversation_id)
        try:
            values = await self.redis.lrange(key, 0, -1)
        except RedisError:
            return await self.fallback.load_all(conversation_id)
        return [ChatTurn.model_validate_json(value) for value in values]

    async def append(self, conversation_id: str, message: ChatTurn) -> None:
        key = _key(conversation_id)
        try:
            await self.redis.rpush(key, message.model_dump_json())
        except RedisError:
            await self.fallback.append(conversation_id, message)

    async def replace_all(self, conversation_id: str, messages: list[ChatTurn]) -> None:
        key = _key(conversation_id)
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.delete(key)
                if messages:
                    await pipe.rpush(key, *[message.model_dump_json() for message in messages])
                await pipe.execute()
        except RedisError:
            await self.fallback.replace_all(conversation_id, messages)


def estimate_token_count(messages: list[ChatTurn]) -> int:
    return TokenCounter().count_messages(messages)


def should_compress(
    messages: list[ChatTurn],
    max_tokens: int,
    config: ShortTermMemoryConfig | None = None,
) -> bool:
    memory_config = config or ShortTermMemoryConfig()
    threshold = int(max_tokens * memory_config.compression_threshold_ratio)
    return estimate_token_count(messages) >= threshold


def summarize_messages(messages: list[ChatTurn], max_items: int = 5) -> str:
    if not messages:
        return ""
    selected = messages[-max_items:]
    return "\n".join(f"{message.role}: {message.content[:240]}" for message in selected)


def _key(conversation_id: str) -> str:
    return f"conversation:{conversation_id}:short_term"
