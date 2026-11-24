from app.core.permissions import requires_approval
from app.tools.adapters import ArxivSearchTool, CalendarDraftTool, ReminderDraftTool, WebSearchTool
from app.tools.finance import FinanceExchangeRateTool
from app.tools.mcp_adapters import BrowserMcpSearchExtractTool, GoogleMapsDirectionsTool, GoogleMapsPlacesTool
from app.schemas.research import ArxivSearchRequest, WebSearchRequest
from app.schemas.tools import WeatherLookupRequest
from app.tools.inputs import (
    BrowserSearchExtractInput,
    CalendarDraftInput,
    FinanceExchangeRateInput,
    MapsDirectionsInput,
    MapsPlacesInput,
    ReminderDraftInput,
)
from app.tools.models import RegisteredTool, ToolAvailabilityStatus, ToolHandler, ToolSpec
from app.tools.weather import WeatherLookupTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        spec: ToolSpec,
        handler: ToolHandler,
        availability_checker=None,
        *,
        input_model=None,
    ) -> None:
        self._tools[spec.name] = RegisteredTool(
            spec=spec.model_copy(update={"requires_approval": requires_approval(spec.permission_level)}),
            handler=handler,
            availability_checker=availability_checker,
            input_model=input_model,
        )

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def list_specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in sorted(self._tools.values(), key=lambda item: item.spec.name)]

    def list_availability(self) -> list[ToolAvailabilityStatus]:
        statuses = []
        for tool in sorted(self._tools.values(), key=lambda item: item.spec.name):
            if tool.availability_checker is not None:
                statuses.append(tool.availability_checker())
                continue
            statuses.append(
                ToolAvailabilityStatus(
                    name=tool.spec.name,
                    capability=tool.spec.capability or tool.spec.name,
                    available=True,
                    status="available",
                    permission_level=tool.spec.permission_level,
                    required_env=tool.spec.required_env,
                    metadata={"provider_name": tool.spec.provider_name},
                )
            )
        return statuses


def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    tools = (
        (WeatherLookupTool(), WeatherLookupRequest),
        (ArxivSearchTool(), ArxivSearchRequest),
        (WebSearchTool(), WebSearchRequest),
        (ReminderDraftTool(), ReminderDraftInput),
        (CalendarDraftTool(), CalendarDraftInput),
        (FinanceExchangeRateTool(), FinanceExchangeRateInput),
        (BrowserMcpSearchExtractTool(), BrowserSearchExtractInput),
        (GoogleMapsDirectionsTool(), MapsDirectionsInput),
        (GoogleMapsPlacesTool(), MapsPlacesInput),
    )
    for tool, input_model in tools:
        registry.register(
            tool.spec,
            tool.run,
            getattr(tool, "availability", None),
            input_model=input_model,
        )
    return registry
