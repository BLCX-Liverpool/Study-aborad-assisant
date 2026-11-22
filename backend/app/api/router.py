from fastapi import APIRouter, Depends, HTTPException

from app.core.config import get_settings

from app.api.routes import (
    assignment,
    auth,
    chat,
    chat_v2,
    dead_letters,
    email,
    email_v2,
    execution,
    files,
    finance,
    fitness,
    health,
    memory,
    notice,
    observability,
    planner,
    rag,
    social_content,
    tools,
    travel,
    wellbeing,
    workflows,
)

api_router = APIRouter()


def require_legacy_long_task_endpoint() -> None:
    settings = get_settings()
    if settings.rabbitmq_workflow_enabled and not settings.legacy_long_task_endpoints_enabled:
        raise HTTPException(
            status_code=410,
            detail="This synchronous long-running endpoint is retired; submit the task through /api/v2/chat.",
        )
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(assignment.router, prefix="/assignment", tags=["assignment"], dependencies=[Depends(require_legacy_long_task_endpoint)])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"], dependencies=[Depends(require_legacy_long_task_endpoint)])
api_router.include_router(chat_v2.router, prefix="/v2/chat", tags=["chat-v2"])
api_router.include_router(dead_letters.router, prefix="/admin/dead-letters", tags=["admin"])
api_router.include_router(email.router, prefix="/email", tags=["email"])
api_router.include_router(email_v2.router, prefix="/v2/email", tags=["email-v2"])
api_router.include_router(execution.router, prefix="/execution", tags=["execution"])
api_router.include_router(files.router, prefix="/files", tags=["files"])
api_router.include_router(finance.router, prefix="/finance", tags=["finance"])
api_router.include_router(fitness.router, prefix="/fitness", tags=["fitness"])
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])
api_router.include_router(notice.router, prefix="/notice", tags=["notice"])
api_router.include_router(observability.router, prefix="/observability", tags=["observability"])
api_router.include_router(planner.router, prefix="/planner", tags=["planner"])
api_router.include_router(rag.router, prefix="/rag", tags=["rag"], dependencies=[Depends(require_legacy_long_task_endpoint)])
api_router.include_router(social_content.router, prefix="/social-content", tags=["social-content"])
api_router.include_router(tools.router, prefix="/tools", tags=["tools"])
api_router.include_router(travel.router, prefix="/travel", tags=["travel"])
api_router.include_router(wellbeing.router, prefix="/wellbeing", tags=["wellbeing"])
api_router.include_router(workflows.router, prefix="/workflows", tags=["workflows"])
