from app.core.permissions import requires_approval
from app.tools.adapters import ArxivSearchTool, CalendarDraftTool, ReminderDraftTool, WebSearchTool
from app.tools.finance import FinanceExchangeRateTool
from app.tools.mcp_adapters import BrowserMcpSearchExtractTool, GoogleMapsDirectionsTool, GoogleMapsPlacesTool
from app.tools.models import RegisteredTool, ToolAvailabilityStatus, ToolHandler, ToolSpec
from app.tools.weather import WeatherLookupTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler, availability_checker=None) -> None:
        self._tools[spec.name] = RegisteredTool(
            spec=spec.model_copy(update={"requires_approval": requires_approval(spec.permission_level)}),
            handler=handler,
            availability_checker=availability_checker,
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
    for tool in (
        WeatherLookupTool(),
        ArxivSearchTool(),
        WebSearchTool(),
        ReminderDraftTool(),
        CalendarDraftTool(),
        FinanceExchangeRateTool(),
        BrowserMcpSearchExtractTool(),
        GoogleMapsDirectionsTool(),
        GoogleMapsPlacesTool(),
    ):
        registry.register(tool.spec, tool.run, getattr(tool, "availability", None))
    return registry
