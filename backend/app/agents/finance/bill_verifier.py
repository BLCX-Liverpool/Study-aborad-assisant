import json

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.schemas.finance import FinanceBillParseOutput


class FinanceBillVerifier:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm

    async def verify(self, output: FinanceBillParseOutput, source_text: str) -> FinanceBillParseOutput:
        if self.llm is None or not output.obligations:
            return output
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "Verify parsed bill obligations against the source text. "
                                "Return JSON with risk_notes and assumptions arrays only. Do not invent amounts or dates."
                            ),
                        ),
                        ChatMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "parsed": output.model_dump(mode="json"),
                                    "source_text": source_text[:4000],
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
            )
            payload = json.loads(response.content)
        except Exception:
            return output
        return output.model_copy(
            update={
                "risk_notes": [*output.risk_notes, *payload.get("risk_notes", [])],
                "assumptions": [*output.assumptions, "LLM bill verifier was applied.", *payload.get("assumptions", [])],
            }
        )
