"""Small deterministic helpers for CSV facts and output normalization."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, TypeVar

T = TypeVar("T")
CENT = Decimal("0.01")


def decimal(value: object | None = None, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or str(value).strip() == "":
        return default
    try:
        return Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def money(value: Decimal | object | None) -> float:
    return float(decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def money_or_none(value: Decimal | object | None) -> float | None:
    if value is None:
        return None
    return money(value)


def timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.strip())


def hours_between(later: datetime | None, earlier: datetime | None) -> float | None:
    if later is None or earlier is None:
        return None
    return round((later - earlier).total_seconds() / 3600, 2)


def unique_stable(values: Iterable[T]) -> list[T]:
    result: list[T] = []
    seen: set[T] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def translated_category(raw: str | None, translations: dict[str, dict[str, str]]) -> str | None:
    if not raw:
        return None
    row = translations.get(raw)
    return (row or {}).get("product_category_name_english") or raw
