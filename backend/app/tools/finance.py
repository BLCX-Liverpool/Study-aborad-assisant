from typing import Any

from app.agents.finance.exchange_rates import StaticExchangeRateProvider
from app.core.permissions import PermissionLevel
from app.tools.models import ToolAvailabilityStatus, ToolSpec


class FinanceExchangeRateTool:
    def __init__(self, provider: StaticExchangeRateProvider | None = None) -> None:
        self.provider = provider or StaticExchangeRateProvider()
        self.spec = ToolSpec(
            name="finance.exchange_rate",
            description="Estimate exchange rates for student budgeting and cash-flow planning.",
            permission_level=PermissionLevel.READ,
            capability="finance.exchange_rate",
            provider_name=self.provider.provider_name,
            input_schema={
                "type": "object",
                "properties": {
                    "base_currency": {"type": "string"},
                    "quote_currency": {"type": "string"},
                },
                "required": ["base_currency", "quote_currency"],
            },
            output_schema={"type": "object"},
        )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        quote = self.provider.quote(
            base_currency=str(arguments.get("base_currency", "GBP")),
            quote_currency=str(arguments.get("quote_currency", "GBP")),
        )
        return quote.model_dump(mode="json")

    def availability(self) -> ToolAvailabilityStatus:
        return ToolAvailabilityStatus(
            name=self.spec.name,
            capability=self.spec.capability or self.spec.name,
            available=True,
            status="available",
            permission_level=self.spec.permission_level,
            metadata={
                "provider_name": self.provider.provider_name,
                "source": "static_estimate",
            },
        )
