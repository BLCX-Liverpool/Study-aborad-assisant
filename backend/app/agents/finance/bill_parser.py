import re
from datetime import UTC, date, datetime, timedelta

from app.schemas.common import PlannedTask
from app.agents.finance.obligations import build_planner_items
from app.schemas.finance import (
    BillType,
    FinanceBillParseOutput,
    FinanceBillParseRequest,
    FinanceCategory,
    FinanceObligation,
)

AMOUNT_RE = re.compile(r"(?P<currency>GBP|USD|EUR|£|\$|€)?\s*(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)", re.I)
DATE_PATTERNS = [
    re.compile(r"\b(?P<date>\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b(?P<date>\d{1,2}/\d{1,2}/\d{4})\b"),
    re.compile(r"\b(?P<date>\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b"),
]

BILL_KEYWORDS: list[tuple[BillType, FinanceCategory, tuple[str, ...]]] = [
    ("tuition", "tuition", ("tuition", "course fee", "学费")),
    ("rent", "rent", ("rent", "tenancy", "landlord", "房租", "租金")),
    ("deposit", "deposit", ("deposit", "押金")),
    ("utilities", "utilities", ("utility", "utilities", "electric", "gas", "water", "bill", "水电", "账单")),
    ("phone", "phone", ("phone", "mobile", "sim", "电话")),
    ("insurance", "insurance", ("insurance", "保险")),
    ("travel", "travel", ("flight", "train", "hotel", "travel", "旅行", "机票")),
]


class FinanceBillParser:
    def parse(self, request: FinanceBillParseRequest) -> FinanceBillParseOutput:
        text = request.raw_text.strip()
        if not text:
            return FinanceBillParseOutput(
                assumptions=["No bill text was provided."],
                risk_notes=["Upload or paste a bill, rent notice, tuition notice, or utility statement before planning payment tasks."],
            )

        obligation = _obligation_from_text(text, request)
        action_items = _action_items(obligation)
        return FinanceBillParseOutput(
            obligations=[obligation],
            action_items=action_items,
            planner_items=build_planner_items([obligation]),
            risk_notes=_risk_notes(obligation),
            assumptions=_assumptions(obligation),
        )


def _obligation_from_text(text: str, request: FinanceBillParseRequest) -> FinanceObligation:
    bill_type, category = _classify_bill(text)
    amount, currency = _extract_amount(text, request.default_currency)
    due_date = _extract_due_date(text)
    return FinanceObligation(
        bill_type=bill_type,
        category=category,
        amount=amount,
        currency=currency,
        due_date=due_date,
        description=_description(bill_type, request.source_name),
        source_name=request.source_name,
        recurring=_looks_recurring(text),
        billing_period=_billing_period(text),
        source_type="parsed_bill",
        evidence_text=_evidence_text(text),
    )


def _classify_bill(text: str) -> tuple[BillType, FinanceCategory]:
    lowered = text.lower()
    for bill_type, category, keywords in BILL_KEYWORDS:
        if any(keyword.lower() in lowered for keyword in keywords):
            return bill_type, category
    return "other", "other"


def _extract_amount(text: str, default_currency: str) -> tuple[float | None, str]:
    candidates = []
    currency_candidates = []
    for match in AMOUNT_RE.finditer(text):
        amount = float(match.group("amount").replace(",", ""))
        if amount == 0:
            continue
        raw_currency = match.group("currency")
        currency = _normalize_currency(raw_currency or default_currency)
        item = (amount, currency)
        candidates.append(item)
        if raw_currency:
            currency_candidates.append(item)
    if not candidates:
        return None, default_currency
    return max(currency_candidates or candidates, key=lambda item: item[0])


def _extract_due_date(text: str) -> date | None:
    lowered = text.lower()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    priority_lines = [line for line in lines if any(keyword in line.lower() for keyword in ("due", "deadline", "pay by", "payment date", "到期", "截止"))]
    for line in [*priority_lines, *lines]:
        parsed = _parse_date_from_line(line)
        if parsed is not None:
            return parsed
    if "tomorrow" in lowered:
        return datetime.now(tz=UTC).date() + timedelta(days=1)
    return None


def _parse_date_from_line(line: str) -> date | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(line)
        if not match:
            continue
        raw = match.group("date")
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    return None


def _normalize_currency(raw: str) -> str:
    mapping = {"£": "GBP", "$": "USD", "€": "EUR"}
    return mapping.get(raw.strip().upper(), raw.strip().upper())


def _looks_recurring(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in ("weekly", "monthly", "quarterly", "termly", "annual", "per month", "recurring", "每周", "每月", "月付", "每年"))


def _billing_period(text: str) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in ("weekly", "per week", "每周")):
        return "weekly"
    if any(keyword in lowered for keyword in ("quarterly", "per quarter", "每季度")):
        return "quarterly"
    if any(keyword in lowered for keyword in ("termly", "per term", "每学期")):
        return "termly"
    if any(keyword in lowered for keyword in ("annual", "yearly", "per year", "每年")):
        return "annual"
    if any(keyword in lowered for keyword in ("monthly", "per month", "recurring", "每月", "月付")):
        return "monthly"
    return "one_time"


def _description(bill_type: BillType, source_name: str | None) -> str:
    prefix = f"{source_name}: " if source_name else ""
    return f"{prefix}{bill_type.replace('_', ' ').title()} obligation"


def _evidence_text(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:240]


def _action_items(obligation: FinanceObligation) -> list[PlannedTask]:
    title = f"Review {obligation.bill_type} payment requirement"
    if obligation.amount is not None:
        title = f"Review {obligation.currency} {obligation.amount:.2f} {obligation.bill_type} payment"
    return [
        PlannedTask(
            title=title,
            description="Verify the amount, due date, recipient, and official payment channel before taking any payment action.",
            source_type="finance",
            deadline=datetime.combine(obligation.due_date, datetime.min.time(), tzinfo=UTC) if obligation.due_date else None,
            estimated_minutes=30,
            priority="high" if obligation.due_date else "medium",
        )
    ]


def _risk_notes(obligation: FinanceObligation) -> list[str]:
    notes = ["Do not pay until the recipient and official payment channel are verified."]
    if obligation.amount is None:
        notes.append("No amount was confidently extracted from the bill text.")
    if obligation.due_date is None:
        notes.append("No due date was confidently extracted from the bill text.")
    if obligation.category == "deposit":
        notes.append("Keep deposit scheme evidence and move-in inventory records.")
    return notes


def _assumptions(obligation: FinanceObligation) -> list[str]:
    assumptions = ["Bill parsing is rule-based and should be checked against the original document."]
    if obligation.recurring:
        assumptions.append("The bill appears recurring based on text keywords.")
    return assumptions
