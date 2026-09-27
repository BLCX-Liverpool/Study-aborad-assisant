from datetime import datetime
from typing import Any

from app.agents.research.arxiv import ArxivSearchClient
from app.agents.research.web_search import WebSearchClient
from app.core.permissions import PermissionLevel
from app.schemas.research import ArxivSearchRequest, WebSearchRequest
from app.tools.models import ToolSpec


class ArxivSearchTool:
    spec = ToolSpec(
        name="research.arxiv.search",
        description="Search ArXiv for assignment research sources.",
        permission_level=PermissionLevel.SEARCH,
        input_schema=ArxivSearchRequest.model_json_schema(),
    )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = ArxivSearchRequest.model_validate(arguments)
        return (await ArxivSearchClient().search(request)).model_dump(mode="json")


class WebSearchTool:
    spec = ToolSpec(
        name="research.web.search",
        description="Search the web for assignment research sources.",
        permission_level=PermissionLevel.SEARCH,
        input_schema=WebSearchRequest.model_json_schema(),
    )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = WebSearchRequest.model_validate(arguments)
        return (await WebSearchClient().search(request)).model_dump(mode="json")


class ReminderDraftTool:
    spec = ToolSpec(
        name="reminder.draft",
        description="Create a local reminder draft payload without sending notifications.",
        permission_level=PermissionLevel.WRITE_DRAFT,
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "remind_at": {"type": "string"},
                "channel": {"type": "string"},
            },
            "required": ["title", "remind_at"],
        },
    )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": str(arguments.get("title", "Reminder")),
            "remind_at": str(arguments.get("remind_at")),
            "channel": str(arguments.get("channel", "in_app")),
            "status": "draft",
        }


class CalendarDraftTool:
    spec = ToolSpec(
        name="calendar.event.draft",
        description="Create a local calendar event draft; no external calendar write is performed.",
        permission_level=PermissionLevel.WRITE_DRAFT,
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["title", "start_time"],
        },
    )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        start_time = _validate_datetime(arguments.get("start_time"))
        end_time = _validate_datetime(arguments.get("end_time")) if arguments.get("end_time") else None
        return {
            "title": str(arguments.get("title", "Calendar event")),
            "start_time": start_time,
            "end_time": end_time,
            "location": arguments.get("location"),
            "status": "draft",
            "external_write_performed": False,
        }


def _validate_datetime(value: Any) -> str:
    text = str(value)
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text
