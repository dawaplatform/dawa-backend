"""Plain-Python data structures used by the moderation pipeline.

Deliberately no Pydantic / no ORM here — the pipeline pushes bytes over the
network and shouldn't drag Django's app-registry into the async path. We
snapshot each `Item` into a `ModerationRow` before scoring so the async
stages never touch the DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ModerationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


@dataclass
class ModerationRow:
    """Snapshot of a single Item taken before the async pipeline runs."""

    item_id: int
    seller_id: Optional[int]
    seller_email: Optional[str]
    title: str
    description: str
    image_urls: list[str]


@dataclass
class ModerationDecision:
    """Result of running the pipeline on a single row."""

    status: ModerationStatus
    reason: Optional[str] = None
    scores: dict[str, Any] = field(default_factory=dict)

