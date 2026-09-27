from fastapi import APIRouter

from app.agents.notice.llm_extractor import LlmNoticeExtractor
from app.agents.notice.parser import NoticeActionParser
from app.core.llm import get_stage_llm_client
from app.schemas.action import NoticeParseRequest, NoticeParseResponse

router = APIRouter()


@router.post("/parse", response_model=NoticeParseResponse)
async def parse_notice(request: NoticeParseRequest) -> NoticeParseResponse:
    return await NoticeActionParser(llm_extractor=LlmNoticeExtractor(get_stage_llm_client("notice"))).parse_async(request)
