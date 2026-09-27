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
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model
        self.default_embedding_model = default_embedding_model

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY is not configured.")

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        model = request.model or self.default_model
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

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        model = request.model or self.default_embedding_model
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
    )


def get_stage_llm_client(stage: str) -> OpenAICompatibleLLM:
    settings = get_settings()
    stage_models = {
        "router": settings.router_llm_model,
        "notice": settings.notice_llm_model,
        "assignment": settings.assignment_llm_model,
        "email": settings.email_llm_model,
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
