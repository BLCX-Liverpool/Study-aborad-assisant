from datetime import UTC, datetime
from typing import Protocol

from app.schemas.finance import ExchangeRateQuote


class ExchangeRateProvider(Protocol):
    provider_name: str

    def quote(self, *, base_currency: str, quote_currency: str) -> ExchangeRateQuote:
        ...


class StaticExchangeRateProvider:
    provider_name = "static_student_budget_estimate"

    def __init__(self, rates_to_gbp: dict[str, float] | None = None) -> None:
        self.rates_to_gbp = {
            "GBP": 1.0,
            "USD": 0.79,
            "EUR": 0.86,
            "CNY": 0.11,
            "HKD": 0.10,
            "CAD": 0.58,
            "AUD": 0.52,
            **(rates_to_gbp or {}),
        }

    def quote(self, *, base_currency: str, quote_currency: str) -> ExchangeRateQuote:
        base = base_currency.upper()
        quote = quote_currency.upper()
        if base == quote:
            return ExchangeRateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=1.0,
                source="user_provided",
                provider_name=self.provider_name,
                as_of=datetime.now(UTC),
                confidence=1.0,
            )
        base_to_gbp = self.rates_to_gbp.get(base)
        quote_to_gbp = self.rates_to_gbp.get(quote)
        if base_to_gbp is None or quote_to_gbp is None or quote_to_gbp == 0:
            return ExchangeRateQuote(
                base_currency=base,
                quote_currency=quote,
                source="unavailable",
                provider_name=self.provider_name,
                as_of=datetime.now(UTC),
                confidence=0.0,
                recoverable_error=f"Missing static exchange rate for {base}->{quote}.",
            )
        return ExchangeRateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=round(base_to_gbp / quote_to_gbp, 6),
            source="static_estimate",
            provider_name=self.provider_name,
            as_of=datetime.now(UTC),
            confidence=0.55,
        )


class CurrencyConverter:
    def __init__(self, provider: ExchangeRateProvider | None = None) -> None:
        self.provider = provider or StaticExchangeRateProvider()
        self._quotes: dict[tuple[str, str], ExchangeRateQuote] = {}

    def convert(self, amount: float, *, base_currency: str, quote_currency: str) -> float | None:
        quote = self.quote(base_currency=base_currency, quote_currency=quote_currency)
        if quote.rate is None:
            return None
        return round(amount * quote.rate, 2)

    def quote(self, *, base_currency: str, quote_currency: str) -> ExchangeRateQuote:
        key = (base_currency.upper(), quote_currency.upper())
        if key not in self._quotes:
            self._quotes[key] = self.provider.quote(base_currency=key[0], quote_currency=key[1])
        return self._quotes[key]

    def quotes(self) -> list[ExchangeRateQuote]:
        return list(self._quotes.values())
