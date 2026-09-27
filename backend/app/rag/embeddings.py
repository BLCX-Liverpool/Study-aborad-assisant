from app.core.llm import EmbeddingRequest, OpenAICompatibleLLM


class EmbeddingService:
    def __init__(self, llm: OpenAICompatibleLLM) -> None:
        self.llm = llm

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self.llm.embed(EmbeddingRequest(inputs=texts))
        return response.embeddings

