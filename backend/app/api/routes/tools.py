from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.tools import ToolCallRequest, ToolCallResult, ToolListResponse, ToolStatusResponse
from app.tools.executor import ToolExecutor
from app.tools.logging import ToolExecutionLogger
from app.tools.registry import build_default_tool_registry

router = APIRouter()


@router.get("", response_model=ToolListResponse)
async def list_tools() -> ToolListResponse:
    registry = build_default_tool_registry()
    return ToolListResponse(tools=registry.list_specs())


@router.get("/status", response_model=ToolStatusResponse)
async def tool_status() -> ToolStatusResponse:
    registry = build_default_tool_registry()
    return ToolStatusResponse(tools=registry.list_availability())


@router.post("/run", response_model=ToolCallResult)
async def run_tool(
    request: ToolCallRequest,
    session: AsyncSession = Depends(get_session),
) -> ToolCallResult:
    result = await ToolExecutor(logger=ToolExecutionLogger(session)).run(request)
    await session.commit()
    return result
