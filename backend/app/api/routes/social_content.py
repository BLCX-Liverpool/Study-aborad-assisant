from fastapi import APIRouter

from app.agents.social_content.llm_generator import LlmSocialCopyGenerator
from app.agents.social_content.service import SocialContentAgentService
from app.core.llm import get_stage_llm_client
from app.schemas.social_content import SocialContentOutput, SocialContentRequest

router = APIRouter()


@router.post("/drafts", response_model=SocialContentOutput)
async def create_social_content(request: SocialContentRequest) -> SocialContentOutput:
    return await SocialContentAgentService(
        llm_generator=LlmSocialCopyGenerator(get_stage_llm_client("social"))
    ).create_content_async(request)
