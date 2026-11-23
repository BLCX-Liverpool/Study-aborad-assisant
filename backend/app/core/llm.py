from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.tracing import capture_current_latency_span


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None
    temperature: float = 0.2
    response_format: dict | None = None


class ChatResponse(BaseModel):
    content: str
    model: str
    raw: dict = Field(default_factory=dict)


class EmbeddingRequest(BaseModel):
    inputs: list[str]
    model: str | None = None


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    raw: dict = Field(default_factory=dict)


class OpenAICompatibleLLM:
    """Minimal OpenAI-compatible client wrapper.

    This is an infrastructure abstraction only. Agent workflows are added in later
    phases according to the approved technical design.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str,
        default_embedding_model: str,
        proxy_url: str | None = None,
        timeout_seconds: float = 45.0,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model
        self.default_embedding_model = default_embedding_model
        self.proxy_url = proxy_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def _client(self):
        from openai import AsyncOpenAI

        http_client = None
        if self.proxy_url:
            import httpx

            http_client = httpx.AsyncClient(proxy=self.proxy_url, timeout=self.timeout_seconds)
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            max_retries=self.max_retries,
            http_client=http_client,
        )

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY is not configured.")

        model = request.model or self.default_model
        async with self._client() as client:
            async with capture_current_latency_span(
                span_name="llm.chat",
                span_type="llm",
                input_json={
                    "model": model,
                    "message_count": len(request.messages),
                    "response_format": request.response_format,
                },
            ) as span_output:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[message.model_dump() for message in request.messages],
                    temperature=request.temperature,
                    response_format=request.response_format,
                )
                span_output["model"] = model
                span_output["choice_count"] = len(response.choices)
        content = response.choices[0].message.content or ""
        return ChatResponse(
            content=content,
            model=model,
            raw=response.model_dump(),
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY is not configured.")

        model = request.model or self.default_embedding_model
        async with self._client() as client:
            async with capture_current_latency_span(
                span_name="llm.embedding",
                span_type="llm",
                input_json={
                    "model": model,
                    "input_count": len(request.inputs),
                },
            ) as span_output:
                response = await client.embeddings.create(
                    model=model,
                    input=request.inputs,
                )
                span_output["model"] = model
                span_output["embedding_count"] = len(response.data)
        embeddings = [item.embedding for item in response.data]
        return EmbeddingResponse(
            embeddings=embeddings,
            model=model,
            raw=response.model_dump(),
        )


def get_llm_client(
    *,
    model: str | None = None,
    embedding_model: str | None = None,
) -> OpenAICompatibleLLM:
    settings = get_settings()
    return OpenAICompatibleLLM(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        default_model=model or settings.llm_model,
        default_embedding_model=embedding_model or settings.embedding_model,
        proxy_url=settings.llm_proxy_url,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def get_stage_llm_client(stage: str) -> OpenAICompatibleLLM:
    settings = get_settings()
    stage_models = {
        "router": settings.router_llm_model,
        "notice": settings.notice_llm_model,
        "assignment": settings.assignment_llm_model,
        "planner": settings.planner_llm_model,
        "email": settings.email_llm_model,
        "travel": settings.travel_llm_model,
        "finance": settings.finance_llm_model,
        "fitness": settings.fitness_llm_model,
        "social": settings.social_llm_model,
        "memory": settings.memory_llm_model,
    }
    stage_embedding_models = {
        "router": settings.router_embedding_model,
    }
    return get_llm_client(
        model=stage_models.get(stage) or settings.llm_model,
        embedding_model=stage_embedding_models.get(stage) or settings.embedding_model,
    )
