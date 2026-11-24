from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM, get_stage_llm_client
from app.tools.models import ToolCallResult, ToolSpec


class ToolCallDraft(BaseModel):
    call_id: str = Field(default_factory=lambda: str(uuid4()))
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


class AgentToolDecision(BaseModel):
    action: Literal["respond", "ask_user", "call_tools"] = "respond"
    reason: str = ""
    tool_calls: list[ToolCallDraft] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class ToolDecisionAgent:
    """Let one domain agent select only from its allowlisted tools."""

    def __init__(self, agent_name: str, llm: OpenAICompatibleLLM | None = None) -> None:
        stage = {"task_planning": "planner", "notice_action": "notice"}.get(agent_name, agent_name)
        self.agent_name = agent_name
        self.llm = llm or get_stage_llm_client(stage)

    async def decide(
        self,
        *,
        message: str,
        business_context: dict[str, Any],
        tools: list[ToolSpec],
        tool_statuses: dict[str, dict[str, Any]] | None = None,
        previous_results: list[ToolCallResult] | None = None,
        round_index: int = 1,
    ) -> AgentToolDecision:
        if not tools:
            return AgentToolDecision(reason="This agent has no allowed tools.")
        prompt_payload = {
            "agent": self.agent_name,
            "message": message,
            "business_context": business_context,
            "round": round_index,
            "allowed_tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "permission_level": tool.permission_level,
                    "availability": (tool_statuses or {}).get(tool.name, {"available": True}),
                }
                for tool in tools
            ],
            "previous_results": [result.model_dump(mode="json") for result in (previous_results or [])],
        }
        system = (
            "You are the tool-decision component inside one domain agent. Select only from allowed_tools. "
            "Return JSON matching {action, reason, tool_calls, missing_information}. "
            "Use call_tools only when fresh external/local tool data is needed; use respond when tools are unnecessary. "
            "Use ask_user when a required argument cannot be derived without inventing user data. "
            "Each tool call must contain call_id, tool_name and arguments that match its input_schema. "
            "Never call a tool already satisfied by previous_results, and never request SEND/DELETE/PAY without explicit approval."
        )
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=json.dumps(prompt_payload, ensure_ascii=False, default=str)),
        ]
        validation_error = None
        for attempt in range(2):
            try:
                response = await self.llm.chat(
                    ChatRequest(messages=messages, temperature=0.0, response_format={"type": "json_object"})
                )
                decision = AgentToolDecision.model_validate(json.loads(response.content))
                allowed = {tool.name for tool in tools}
                decision.tool_calls = [call for call in decision.tool_calls if call.tool_name in allowed]
                if decision.action == "call_tools" and not decision.tool_calls:
                    decision.action = "respond"
                return decision
            except (ValidationError, json.JSONDecodeError) as exc:
                validation_error = exc
                if attempt == 0:
                    messages.append(
                        ChatMessage(
                            role="user",
                            content=f"Correct the JSON once. Validation error: {exc}",
                        )
                    )
                    continue
                break
            except Exception:
                break
        fallback = fallback_tool_decision(
            agent_name=self.agent_name,
            business_context=business_context,
            allowed_tools={
                tool.name
                for tool in tools
                if (tool_statuses or {}).get(tool.name, {"available": True}).get("available", True)
            },
            round_index=round_index,
        )
        if validation_error is not None:
            fallback.reason = f"Deterministic fallback after invalid tool decision: {validation_error}"
        return fallback


def fallback_tool_decision(
    *,
    agent_name: str,
    business_context: dict[str, Any],
    allowed_tools: set[str],
    round_index: int,
) -> AgentToolDecision:
    if round_index > 1:
        return AgentToolDecision(reason="No deterministic follow-up tool call is required.")
    builders = {
        "travel": _travel_calls,
        "finance": _finance_calls,
        "assignment": _assignment_calls,
        "task_planning": _planning_calls,
        "notice_action": _planning_calls,
    }
    calls = builders.get(agent_name, lambda _: [])(business_context)
    calls = [call for call in calls if call.tool_name in allowed_tools][:8]
    if not calls:
        return AgentToolDecision(reason="No safe deterministic tool call was inferred.")
    return AgentToolDecision(
        action="call_tools",
        reason="Deterministic domain fallback selected tools from validated business context.",
        tool_calls=calls,
    )


def _travel_calls(context: dict[str, Any]) -> list[ToolCallDraft]:
    origin = context.get("origin")
    destination = context.get("destination")
    if not origin or not destination:
        return []
    calls = [
        ToolCallDraft(
            tool_name="travel.maps.directions",
            arguments={
                "origin": origin,
                "destination": destination,
                "mode": "transit",
                "depart_at": _iso(context.get("depart_at")),
            },
        )
    ]
    if context.get("depart_at"):
        calls.append(
            ToolCallDraft(
                tool_name="weather.lookup",
                arguments={
                    "location": destination,
                    "start_date": str(_date_part(context.get("depart_at"))),
                    "days": _travel_days(context.get("depart_at"), context.get("return_at")),
                },
            )
        )
    calls.append(
        ToolCallDraft(
            tool_name="travel.maps.places",
            arguments={
                "location": destination,
                "query": _place_query(str(context.get("purpose") or "other")),
                "max_results": 3,
            },
        )
    )
    notes = str(context.get("notes") or "")
    if _needs_web_travel_research(notes):
        calls.append(
            ToolCallDraft(
                tool_name="browser.mcp.search",
                arguments={
                    "query": f"{destination} student travel recommendations {notes}".strip(),
                    "search_depth": "basic",
                    "max_results": 5,
                },
            )
        )
    return calls


def _finance_calls(context: dict[str, Any]) -> list[ToolCallDraft]:
    target = str(context.get("target_currency") or context.get("currency") or "GBP").upper()
    bases = {str(context.get("currency") or target).upper()}
    for collection in (context.get("expenses") or [], context.get("travel_budget_items") or []):
        for item in collection:
            if isinstance(item, dict) and item.get("currency"):
                bases.add(str(item["currency"]).upper())
    return [
        ToolCallDraft(
            tool_name="finance.exchange_rate",
            arguments={"base_currency": base, "quote_currency": target},
        )
        for base in sorted(bases)
        if base != target
    ]


def _assignment_calls(context: dict[str, Any]) -> list[ToolCallDraft]:
    analysis = context.get("analysis") if isinstance(context.get("analysis"), dict) else context
    queries = analysis.get("research_queries") or []
    if not queries:
        query = analysis.get("title") or analysis.get("objective")
        queries = [query] if query else []
    calls: list[ToolCallDraft] = []
    for query in queries[:3]:
        if not query:
            continue
        calls.extend(
            [
                ToolCallDraft(
                    tool_name="research.arxiv.search",
                    arguments={"query": query, "max_results": 3},
                ),
                ToolCallDraft(
                    tool_name="browser.mcp.search",
                    arguments={"query": query, "search_depth": "basic", "max_results": 5},
                ),
            ]
        )
    return calls


def _needs_web_travel_research(notes: str) -> bool:
    lowered = notes.lower()
    return any(
        token in lowered
        for token in (
            "攻略",
            "推荐",
            "景点",
            "guide",
            "recommend",
            "attraction",
            "policy",
            "官网",
        )
    )


def _planning_calls(context: dict[str, Any]) -> list[ToolCallDraft]:
    calls: list[ToolCallDraft] = []
    for reminder in context.get("reminders") or []:
        if isinstance(reminder, dict) and reminder.get("title") and reminder.get("remind_at"):
            calls.append(
                ToolCallDraft(
                    tool_name="reminder.draft",
                    arguments={
                        "title": reminder["title"],
                        "remind_at": _iso(reminder["remind_at"]),
                        "channel": reminder.get("channel") or "in_app",
                    },
                )
            )
    for event in context.get("events") or []:
        if isinstance(event, dict) and event.get("title") and event.get("start_time"):
            calls.append(
                ToolCallDraft(
                    tool_name="calendar.event.draft",
                    arguments={
                        "title": event["title"],
                        "start_time": _iso(event["start_time"]),
                        "end_time": _iso(event.get("end_time")),
                        "location": event.get("location"),
                    },
                )
            )
    return calls


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _date_part(value: Any):
    if hasattr(value, "date"):
        return value.date()
    return str(value).split("T", 1)[0]


def _travel_days(depart_at: Any, return_at: Any) -> int:
    try:
        depart = depart_at if isinstance(depart_at, datetime) else datetime.fromisoformat(str(depart_at))
        returned = return_at if isinstance(return_at, datetime) else datetime.fromisoformat(str(return_at))
        return max(1, min((returned.date() - depart.date()).days + 1, 7))
    except (TypeError, ValueError):
        return 1


def _place_query(purpose: str) -> str:
    return {
        "academic_trip": "university campus services",
        "visa_or_immigration": "visa application centre",
        "airport_arrival": "airport transfer and student services",
        "city_trip": "student friendly attractions",
    }.get(purpose, "student friendly services")
