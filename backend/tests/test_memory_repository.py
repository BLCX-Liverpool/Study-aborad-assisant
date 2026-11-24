from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models import Memory
from app.memory.repository import LongTermMemoryRepository


@pytest.mark.asyncio
async def test_long_term_memory_search_uses_pgvector_top_k() -> None:
    memory = Memory(
        id="memory-1",
        user_id="user-1",
        namespace="travel",
        memory_type="user_preference",
        content="User prefers quiet hotels near public transport.",
        confidence=0.9,
        access_policy_json={"confirmed": True, "rejected": False},
        embedding=[1.0, *([0.0] * 1535)],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class Result:
        def all(self):
            return [(memory, 0.94)]

    class Session:
        def __init__(self) -> None:
            self.statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    session = Session()
    repository = LongTermMemoryRepository(session)  # type: ignore[arg-type]

    results = await repository.search(
        user_id="user-1",
        query="quiet hotel",
        namespaces=["shared", "travel"],
        top_k=3,
        query_embedding=[1.0, *([0.0] * 1535)],
    )

    assert session.statement is not None
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "memories.embedding <=>" in sql
    assert "ORDER BY memories.embedding <=>" in sql
    assert "LIMIT" in sql
    assert results[0].id == "memory-1"
    assert results[0].score == pytest.approx(0.94)
