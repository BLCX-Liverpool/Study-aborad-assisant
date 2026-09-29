from fastapi import APIRouter

from app.api.routes import (
    assignment,
    chat,
    email,
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
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(assignment.router, prefix="/assignment", tags=["assignment"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(email.router, prefix="/email", tags=["email"])
api_router.include_router(execution.router, prefix="/execution", tags=["execution"])
api_router.include_router(files.router, prefix="/files", tags=["files"])
api_router.include_router(finance.router, prefix="/finance", tags=["finance"])
api_router.include_router(fitness.router, prefix="/fitness", tags=["fitness"])
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])
api_router.include_router(notice.router, prefix="/notice", tags=["notice"])
api_router.include_router(observability.router, prefix="/observability", tags=["observability"])
api_router.include_router(planner.router, prefix="/planner", tags=["planner"])
api_router.include_router(rag.router, prefix="/rag", tags=["rag"])
api_router.include_router(social_content.router, prefix="/social-content", tags=["social-content"])
api_router.include_router(tools.router, prefix="/tools", tags=["tools"])
api_router.include_router(travel.router, prefix="/travel", tags=["travel"])
api_router.include_router(wellbeing.router, prefix="/wellbeing", tags=["wellbeing"])
