from app.memory.continuity import TopicContinuityDetector
from app.memory.candidates import MemoryCandidateService
from app.memory.compression import MemoryCompressor
from app.memory.llm_judge import TopicAmbiguityJudge
from app.memory.namespaces import infer_memory_namespace
from app.memory.query_rewrite import QueryRewriter
from app.memory.repository import ConversationRepository, LongTermMemoryRepository
from app.memory.router import MemoryRouter
from app.memory.short_term import InMemoryShortTermMemoryStore, ShortTermMemoryConfig, should_compress, summarize_messages
from app.core.llm import get_stage_llm_client
from app.rag.embeddings import EmbeddingService
from app.schemas.chat import ChatRequest, ChatTurn
from app.schemas.memory import LongTermMemoryItem, MemoryCandidateInput, MemoryContext
from app.schemas.router import RouterOutput


class MemoryManager:
    def __init__(
        self,
        short_term_store: InMemoryShortTermMemoryStore | None = None,
        conversation_repository: ConversationRepository | None = None,
        long_term_repository: LongTermMemoryRepository | None = None,
        memory_router: MemoryRouter | None = None,
        continuity_detector: TopicContinuityDetector | None = None,
        query_rewriter: QueryRewriter | None = None,
        compressor: MemoryCompressor | None = None,
        ambiguity_judge: TopicAmbiguityJudge | None = None,
        embedding_service: EmbeddingService | None = None,
        max_context_tokens: int = 1200,
    ) -> None:
        memory_llm = get_stage_llm_client("memory")
        self.short_term_store = short_term_store or InMemoryShortTermMemoryStore()
        self.conversation_repository = conversation_repository
        self.long_term_repository = long_term_repository
        self.memory_router = memory_router or MemoryRouter(memory_llm)
        self.continuity_detector = continuity_detector or TopicContinuityDetector()
        self.query_rewriter = query_rewriter or QueryRewriter(memory_llm)
        self.compressor = compressor or MemoryCompressor(memory_llm)
        self.ambiguity_judge = ambiguity_judge or TopicAmbiguityJudge(memory_llm)
        self.embedding_service = embedding_service or EmbeddingService(memory_llm)
        self.max_context_tokens = max_context_tokens

    async def build_context(
        self,
        *,
        request: ChatRequest,
        conversation_id: str,
        router_output: RouterOutput,
    ) -> MemoryContext:
        stored_recent = await self.short_term_store.load_recent(conversation_id, limit=10)
        recent_messages = stored_recent or request.history[-10:]
        topic = self.continuity_detector.detect(request.message, recent_messages)
        topic = await self.ambiguity_judge.judge(
            query=request.message,
            recent_messages=recent_messages,
            initial=topic,
        )
        rewrite = await self.query_rewriter.rewrite_async(
            query=request.message,
            topic=topic,
            recent_messages=recent_messages,
        )
        routing = await self.memory_router.route_async(
            query=rewrite.rewritten_query,
            router_output=router_output,
            recent_messages=recent_messages,
            topic=topic,
        )

        long_term_memories: list[LongTermMemoryItem] = []
        query_embedding = await self._embed_optional(rewrite.rewritten_query)
        if routing.need_long_term_memory and self.long_term_repository is not None:
            long_term_memories = await self.long_term_repository.search(
                user_id=request.user_id,
                query=rewrite.rewritten_query,
                namespaces=list(routing.namespaces),
                top_k=5,
                query_embedding=query_embedding,
            )

        return MemoryContext(
            routing=routing,
            topic=topic,
            query_rewrite=rewrite,
            recent_messages=recent_messages,
            long_term_memories=long_term_memories,
            prompt_context=_build_prompt_context(recent_messages, long_term_memories),
        )

    async def update_after_response(
        self,
        *,
        request: ChatRequest,
        conversation_id: str,
        response_text: str,
        router_output: RouterOutput,
        topic_summary: str | None = None,
    ) -> None:
        user_turn = ChatTurn(role="user", content=request.message)
        assistant_turn = ChatTurn(role="assistant", content=response_text)
        await self.short_term_store.append(conversation_id, user_turn)
        await self.short_term_store.append(conversation_id, assistant_turn)

        if self.conversation_repository is not None:
            await self.conversation_repository.ensure_conversation(
                conversation_id=conversation_id,
                user_id=request.user_id,
                topic_summary=topic_summary,
            )
            await self.conversation_repository.append_message(
                conversation_id=conversation_id,
                user_id=request.user_id,
                message=user_turn,
                metadata={"source": "chat"},
            )
            await self.conversation_repository.append_message(
                conversation_id=conversation_id,
                user_id=request.user_id,
                message=assistant_turn,
                metadata={"source": "assistant", "intent": router_output.primary_intent},
            )

        if self.long_term_repository is not None and router_output.primary_intent != "wellbeing":
            candidates = [
                MemoryCandidateInput(
                    namespace=infer_memory_namespace(content),
                    content=content,
                    source_type="conversation",
                    source_id=conversation_id,
                    confidence=0.7,
                    confirmed=_has_explicit_memory_confirmation(request.message),
                    agent_name=router_output.primary_intent,
                )
                for content in _extract_memory_candidates(request.message)
            ]
            if candidates:
                await MemoryCandidateService(
                    self.long_term_repository,
                    embedding_service=self.embedding_service,
                ).persist_candidates(
                    user_id=request.user_id,
                    candidates=candidates,
                    requested=True,
                    confirmed=_has_explicit_memory_confirmation(request.message),
                    source_id=conversation_id,
                )

        await self._compress_short_term_if_needed(
            user_id=request.user_id,
            conversation_id=conversation_id,
            router_output=router_output,
        )

        if self.conversation_repository is not None:
            await self.conversation_repository.commit()

    async def _embed_optional(self, text: str) -> list[float] | None:
        if self.embedding_service is None:
            return None
        try:
            embeddings = await self.embedding_service.embed_texts([text])
        except Exception:
            return None
        return embeddings[0] if embeddings else None

    async def _compress_short_term_if_needed(
        self,
        *,
        user_id: str,
        conversation_id: str,
        router_output: RouterOutput,
    ) -> str:
        load_all = getattr(self.short_term_store, "load_all", None)
        replace_all = getattr(self.short_term_store, "replace_all", None)
        if load_all is None or replace_all is None:
            return ""
        messages: list[ChatTurn] = await load_all(conversation_id)
        config = getattr(self.short_term_store, "config", ShortTermMemoryConfig())
        if not should_compress(messages, self.max_context_tokens, config):
            return ""

        retain_count = max(2, getattr(config, "retained_recent_messages", 6))
        retained = messages[-retain_count:] if len(messages) > retain_count else []
        to_compress = messages[:-retain_count] if retained else messages
        summary = await self.compressor.compress(to_compress)
        if not summary:
            return ""
        compressed_turn = ChatTurn(role="system", content=f"短期记忆压缩摘要：{summary}")
        await replace_all(conversation_id, [compressed_turn, *retained])

        if self.long_term_repository is not None:
            embedding = await self._embed_optional(summary)
            await self.long_term_repository.add_memory(
                user_id=user_id,
                namespace=str(infer_memory_namespace(summary)),
                memory_type="conversation_summary",
                content=summary,
                source_type="short_term_compression",
                source_id=conversation_id,
                confidence=0.75,
                embedding=embedding,
                access_policy={
                    "requires_user_confirmation": False,
                    "confirmed": True,
                    "rejected": False,
                    "reason": "Generated by short-term memory compression at the configured threshold.",
                    "agent_name": router_output.primary_intent,
                },
            )
        return summary


def _build_prompt_context(
    recent_messages: list[ChatTurn],
    long_term_memories: list[LongTermMemoryItem],
    compressed_summary: str = "",
) -> str:
    parts = []
    if compressed_summary:
        parts.append("Compressed recent context:\n" + compressed_summary)
    recent_summary = summarize_messages(recent_messages)
    if recent_summary:
        parts.append("Recent conversation:\n" + recent_summary)
    if long_term_memories:
        memory_lines = "\n".join(
            f"- [{memory.namespace}] {memory.content}" for memory in long_term_memories
        )
        parts.append("Long-term memories:\n" + memory_lines)
    return "\n\n".join(parts)


def _extract_memory_candidates(message: str) -> list[str]:
    stable_signals = (
        "我不吃",
        "我不喜欢",
        "我喜欢",
        "我的预算",
        "每月预算",
        "my budget",
        "i prefer",
        "i don't eat",
        "i do not eat",
    )
    lowered = message.lower()
    if any(signal in lowered for signal in stable_signals):
        return [message[:500]]
    return []


def _has_explicit_memory_confirmation(message: str) -> bool:
    lowered = message.lower()
    return any(signal in lowered for signal in ("记住", "请记住", "remember this", "you can remember"))
