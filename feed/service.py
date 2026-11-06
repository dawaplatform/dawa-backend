"""Builds the ranked home feed from the Django ORM and caches it per session."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from DawaApp.models import Chat, Item, ItemImage, ReportAbuse, Wishlist
from feed import config as C
from feed import scoring

_VERSION_KEY = "feed:version"


@dataclass
class RankedFeed:
    ids: list[int]
    badges: dict[int, str]


def bump_version() -> None:
    try:
        cache.incr(_VERSION_KEY)
    except ValueError:
        cache.set(_VERSION_KEY, 2, None)


def version() -> int:
    return cache.get_or_set(_VERSION_KEY, 1, None)


def _counts(model, ids: list[int], q: Q | None = None) -> dict[int, int]:
    qs = model.objects.filter(item_id__in=ids)
    if q is not None:
        qs = qs.filter(q)
    return {row["item_id"]: row["n"] for row in qs.values("item_id").annotate(n=Count("id"))}


def _candidates(category_id: int | None, subcategory_id: int | None) -> list[scoring.Candidate]:
    qs = Item.objects.filter(approval_status="Approved", item_status="Available")
    if category_id:
        qs = qs.filter(item_subcategory__subcategory_category_id=category_id)
    if subcategory_id:
        qs = qs.filter(item_subcategory_id=subcategory_id)
    rows = list(
        qs.order_by("-created_at").values(
            "id", "seller_id", "item_subcategory_id", "item_name", "item_description", "item_price",
            "item_location", "created_at", "item_promoted", "subscription_package", "views_count", "shares_count",
        )[: C.RANKING_FETCH_LIMIT]
    )
    ids = [r["id"] for r in rows]
    photos = _counts(ItemImage, ids)
    wishes = _counts(Wishlist, ids, Q(is_wished=True))
    chats = _counts(Chat, ids)
    reports = _counts(ReportAbuse, ids, Q(status__in=["Pending", "In Review"]))
    return [
        scoring.Candidate(
            id=r["id"],
            seller_id=r["seller_id"],
            subcategory_id=r["item_subcategory_id"],
            name=r["item_name"] or "",
            description=r["item_description"] or "",
            price=float(r["item_price"] or 0),
            location=r["item_location"] or "",
            created_at=r["created_at"],
            promoted=bool(r["item_promoted"]) or r["subscription_package"] in C.PAID_PACKAGES,
            photos=photos.get(r["id"], 0),
            views=r["views_count"] or 0,
            wishes=wishes.get(r["id"], 0),
            chats=chats.get(r["id"], 0),
            shares=r["shares_count"] or 0,
            reports=reports.get(r["id"], 0),
        )
        for r in rows
    ]


def rank(
    *, session: str, category_id: int | None = None, subcategory_id: int | None = None, location: str | None = None
) -> RankedFeed:
    now = timezone.now()
    cands = _candidates(category_id, subcategory_id)
    scores = scoring.score_all(cands, now, session=session, location=location)
    ordered = scoring.diversify(sorted(cands, key=lambda c: (-scores[c.id], -c.id)))
    trending = scoring.trending_ids(cands, now)
    badges = {c.id: b for c in ordered if (b := scoring.badge_for(c, trending, now))}
    return RankedFeed(ids=[c.id for c in ordered], badges=badges)


def ranked_for_session(
    *, session: str, category_id: int | None = None, subcategory_id: int | None = None, location: str | None = None
) -> RankedFeed:
    raw = f"{version()}|{session}|{category_id}|{subcategory_id}|{(location or '').lower()}"
    key = "feed:rank:" + hashlib.sha1(raw.encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    feed = rank(session=session, category_id=category_id, subcategory_id=subcategory_id, location=location)
    cache.set(key, feed, C.SESSION_TTL_SECONDS)
    return feed


def page_items(ids: list[int]) -> list[Item]:
    by_id = (
        Item.objects.filter(id__in=ids, approval_status="Approved", item_status="Available")
        .select_related("item_subcategory__subcategory_category")
        .prefetch_related("images")
        .in_bulk()
    )
    return [by_id[i] for i in ids if i in by_id]
