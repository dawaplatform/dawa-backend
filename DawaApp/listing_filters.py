"""Optional filters and sorting for the public listing endpoint."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from django.db.models import F, QuerySet

SORTS = {
    "newest": ("-created_at", "-id"),
    "price_asc": ("item_price", "-id"),
    "price_desc": ("-item_price", "-id"),
    "popular": (F("views_count").desc(nulls_last=True), "-id"),
}


class InvalidFilter(ValueError):
    """Raised for a filter value that cannot be interpreted."""


def _price(params: Mapping[str, Any], key: str) -> Decimal | None:
    raw = params.get(key)
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        raise InvalidFilter(f"{key} must be a number")
    if value < 0:
        raise InvalidFilter(f"{key} cannot be negative")
    return value


def apply_listing_filters(items: QuerySet, params: Mapping[str, Any]) -> QuerySet:
    min_price, max_price = _price(params, "min_price"), _price(params, "max_price")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise InvalidFilter("min_price cannot be greater than max_price")
    if min_price is not None:
        items = items.filter(item_price__gte=min_price)
    if max_price is not None:
        items = items.filter(item_price__lte=max_price)

    location = str(params.get("location") or "").strip()[:100]
    if location:
        items = items.filter(item_location__icontains=location)

    if str(params.get("negotiable")).lower() in ("true", "1"):
        items = items.filter(item_negotiable=True)

    sort = params.get("sort") or "newest"
    if sort not in SORTS:
        raise InvalidFilter(f"sort must be one of: {', '.join(SORTS)}")
    return items.order_by(*SORTS[sort])
