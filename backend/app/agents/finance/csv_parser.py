import csv
from io import StringIO

from app.schemas.finance import ExpenseItem, FinanceCategory

CATEGORY_KEYWORDS: list[tuple[FinanceCategory, tuple[str, ...]]] = [
    ("rent", ("rent", "房租", "租金")),
    ("deposit", ("deposit", "押金")),
    ("tuition", ("tuition", "学费")),
    ("utilities", ("utility", "utilities", "electric", "gas", "water", "账单", "水电")),
    ("groceries", ("grocery", "groceries", "food", "supermarket", "餐", "超市")),
    ("transport", ("transport", "train", "bus", "metro", "uber", "交通")),
    ("phone", ("phone", "mobile", "sim", "电话")),
    ("insurance", ("insurance", "保险")),
    ("travel", ("flight", "hotel", "travel", "trip", "旅行", "机票")),
    ("income", ("income", "salary", "part-time", "兼职", "工资")),
    ("emergency_fund", ("emergency", "备用金")),
]


class ExpenseCsvParser:
    def parse(self, content: str, default_currency: str) -> list[ExpenseItem]:
        rows = csv.DictReader(StringIO(content.strip()))
        expenses: list[ExpenseItem] = []

        for row in rows:
            amount = _parse_amount(row)
            if amount is None:
                continue
            description = _first(row, "description", "name", "merchant", "备注", "描述")
            category_text = _first(row, "category", "类别") or description or ""
            expenses.append(
                ExpenseItem(
                    category=_classify_category(category_text),
                    amount=amount,
                    currency=_first(row, "currency", "币种") or default_currency,
                    description=description,
                    recurring=_parse_bool(_first(row, "recurring", "is_recurring", "是否 recurring", "是否重复")),
                )
            )

        return expenses


def _parse_amount(row: dict[str, str]) -> float | None:
    raw = _first(row, "amount", "cost", "price", "金额")
    if raw is None:
        return None
    try:
        return abs(float(raw.replace(",", "").strip()))
    except ValueError:
        return None


def _first(row: dict[str, str], *keys: str) -> str | None:
    normalized = {key.strip().lower(): value for key, value in row.items() if key is not None}
    for key in keys:
        value = normalized.get(key.lower())
        if value is not None and value.strip():
            return value.strip()
    return None


def _classify_category(text: str) -> FinanceCategory:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword.lower() in lowered for keyword in keywords):
            return category
    return "other"


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "是"}
