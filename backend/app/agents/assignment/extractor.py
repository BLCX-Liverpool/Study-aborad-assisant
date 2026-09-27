import json

from app.agents.assignment.evidence import source_context_from_chunks
from app.agents.assignment.prompts import (
    ASSIGNMENT_EXTRACTION_SYSTEM_PROMPT,
    build_assignment_extraction_prompt,
)
from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.documents.models import DocumentChunkDraft
from app.schemas.assignment import AssignmentAnalysis


class RequirementExtractionError(RuntimeError):
    pass


class AssignmentRequirementExtractor:
    def __init__(self, llm: OpenAICompatibleLLM) -> None:
        self.llm = llm

    async def extract(self, chunks: list[DocumentChunkDraft]) -> AssignmentAnalysis:
        source_context = source_context_from_chunks(chunks)
        schema_json = json.dumps(AssignmentAnalysis.model_json_schema(), ensure_ascii=False)
        prompt = build_assignment_extraction_prompt(schema_json, source_context)

        response = await self.llm.chat(
            ChatRequest(
                messages=[
                    ChatMessage(role="system", content=ASSIGNMENT_EXTRACTION_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=prompt),
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
        )

        try:
            payload = json.loads(response.content)
            return AssignmentAnalysis.model_validate(payload)
        except Exception as exc:
            raise RequirementExtractionError("Failed to validate AssignmentAnalysis output.") from exc

