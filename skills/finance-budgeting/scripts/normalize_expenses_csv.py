#!/usr/bin/env python3
"""Normalize a student expense CSV into JSON lines.

This helper is intentionally small and local. It does not call any external API
and does not perform currency conversion.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--currency", default="GBP")
    args = parser.parse_args()

    with args.input_csv.open("r", encoding="utf-8-sig", newline="") as file:
        rows = csv.DictReader(file)
        for row in rows:
            amount = parse_amount(first(row, "amount", "cost", "price", "金额"))
            if amount is None:
                continue
            description = first(row, "description", "name", "merchant", "备注", "描述") or ""
            category_text = first(row, "category", "类别") or description
            payload = {
                "category": classify_category(category_text),
                "amount": amount,
                "currency": first(row, "currency", "币种") or args.currency,
                "description": description,
                "recurring": parse_bool(first(row, "recurring", "is_recurring", "是否重复")),
            }
            print(json.dumps(payload, ensure_ascii=False))

    return 0


def first(row: dict[str, str], *keys: str) -> str | None:
    normalized = {key.strip().lower(): value for key, value in row.items() if key is not None}
    for key in keys:
        value = normalized.get(key.lower())
        if value is not None and value.strip():
            return value.strip()
    return None


def parse_amount(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return abs(float(value.replace(",", "").strip()))
    except ValueError:
        return None


def classify_category(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword.lower() in lowered for keyword in keywords):
            return category
    return "other"


def parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "是"}


if __name__ == "__main__":
    raise SystemExit(main())
