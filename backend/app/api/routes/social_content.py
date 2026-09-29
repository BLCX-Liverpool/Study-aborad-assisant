from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.social_content.llm_generator import LlmSocialCopyGenerator
from app.agents.social_content.service import SocialContentAgentService
from app.core.database import get_session
from app.core.llm import get_stage_llm_client
from app.memory.candidates import MemoryCandidateService
from app.memory.repository import LongTermMemoryRepository
from app.schemas.social_content import SocialContentOutput, SocialContentRequest

router = APIRouter()


@router.post("/drafts", response_model=SocialContentOutput)
async def create_social_content(
    request: SocialContentRequest,
    session: AsyncSession = Depends(get_session),
) -> SocialContentOutput:
    output = await SocialContentAgentService(
        llm_generator=LlmSocialCopyGenerator(get_stage_llm_client("social"))
    ).create_content_async(request)
    memory_confirmation = await MemoryCandidateService(LongTermMemoryRepository(session)).persist_candidates(
        user_id=request.user_id,
        candidates=output.memory_candidates,
        requested=request.save_memory_candidates,
        confirmed=request.memory_confirmed,
    )
    await session.commit()
    return output.model_copy(update={"memory_confirmation": memory_confirmation})
