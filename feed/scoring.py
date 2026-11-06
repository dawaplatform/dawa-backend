"""Pure scoring/ordering helpers (no DB access) so they are easy to test."""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from feed import config as C


@dataclass
class Candidate:
    id: int
    seller_id: int
    subcategory_id: int
    name: str
    description: str
    price: float
    location: str
    created_at: datetime | None
    promoted: bool
    photos: int = 0
    views: int = 0
    wishes: int = 0
    chats: int = 0
    shares: int = 0
    reports: int = 0


def _scaled(length: int, full: int, half: int, points: float) -> float:
    return points if length >= full else points / 2 if length >= half else 0.0


def quality(c: Candidate) -> float:
    score = 35.0 if c.photos >= 3 else 30.0 if c.photos == 2 else 20.0 if c.photos == 1 else 0.0
    score += _scaled(len(c.name.strip()), 10, 3, 10.0)
    score += _scaled(len(c.description.strip()), 80, 30, 20.0)
    score += 20.0 if c.price > 0 else 0.0
    score += 15.0 if c.location.strip() else 0.0
    return score


def age_hours(c: Candidate, now: datetime) -> float:
    if c.created_at is None:
        return float(C.FRESHNESS_BANDS[-1][0])
    return max((now - c.created_at).total_seconds() / 3600.0, 0.0)


def freshness(c: Candidate, now: datetime) -> float:
    hours = age_hours(c, now)
    for limit, value in C.FRESHNESS_BANDS:
        if hours < limit:
            return value
    return C.FRESHNESS_FLOOR


def engagement(c: Candidate) -> float:
    return float(c.views + 2 * c.wishes + 2 * c.shares + 4 * c.chats - 5 * c.reports)


def decayed_engagement(c: Candidate, now: datetime) -> float:
    return engagement(c) / (1.0 + age_hours(c, now) / 24.0) ** 1.5


def location_fit(c: Candidate, location: str | None) -> bool:
    if not location:
        return False
    item_loc = c.location.lower()
    return any(tok in item_loc for tok in location.lower().replace(",", " ").split() if len(tok) >= 3)


def jitter(session: str, item_id: int) -> float:
    if not session:
        return 0.0
    digest = hashlib.sha1(f"{session}:{item_id}".encode()).digest()
    unit = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return (unit * 2 - 1) * C.SESSION_JITTER


def trending_ids(cands: list[Candidate], now: datetime) -> set[int]:
    scored = [
        (decayed_engagement(c, now), c.id)
        for c in cands
        if c.views >= C.TRENDING_MIN_VIEWS and (c.wishes + c.chats + c.shares) >= C.TRENDING_MIN_ACTIONS
    ]
    scored = [s for s in scored if s[0] > 0]
    if not scored:
        return set()
    keep = max(1, math.ceil(C.TRENDING_TOP_SHARE * len(cands)))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return {item_id for _, item_id in scored[:keep]}


def score_all(
    cands: list[Candidate], now: datetime, *, session: str = "", location: str | None = None
) -> dict[int, float]:
    decayed = {c.id: max(decayed_engagement(c, now), 0.0) for c in cands}
    top = max(decayed.values(), default=0.0) or 1.0
    scores: dict[int, float] = {}
    for c in cands:
        s = quality(c) * C.QUALITY_WEIGHT / 100.0
        s += freshness(c, now) * C.FRESHNESS_WEIGHT / 100.0
        s += (decayed[c.id] / top * 100.0) * C.ENGAGEMENT_WEIGHT / 100.0
        s += C.PROMOTED_BOOST if c.promoted else 0.0
        s += C.LOCATION_BOOST if location_fit(c, location) else 0.0
        s -= C.REPORT_PENALTY if c.reports > 0 else 0.0
        s += jitter(session, c.id)
        scores[c.id] = s
    return scores


def _trailing_run(out: list[Candidate], subcategory_id: int) -> int:
    run = 0
    for c in reversed(out):
        if c.subcategory_id != subcategory_id:
            break
        run += 1
    return run


def diversify(ranked: list[Candidate]) -> list[Candidate]:
    """Keep score order but cap items per seller per block and avoid long same-subcategory runs."""
    pending = list(ranked)
    out: list[Candidate] = []
    sellers: Counter[int] = Counter()
    while pending:
        if len(out) % C.BLOCK_SIZE == 0:
            sellers.clear()
        pick = 0
        for idx, c in enumerate(pending):
            if sellers[c.seller_id] < C.SELLER_CAP_PER_BLOCK and _trailing_run(out, c.subcategory_id) < C.MAX_SAME_SUBCATEGORY_RUN:
                pick = idx
                break
        chosen = pending.pop(pick)
        sellers[chosen.seller_id] += 1
        out.append(chosen)
    return out


def badge_for(c: Candidate, trending: set[int], now: datetime) -> str | None:
    if c.id in trending:
        return "trending"
    if c.promoted:
        return "promoted"
    if age_hours(c, now) < C.NEW_BADGE_HOURS:
        return "new"
    return None
