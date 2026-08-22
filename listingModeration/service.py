"""Django ORM adapter for the moderation queue.

There is no separate queue table — `Item.approval_status == 'Pending'` IS
the queue. The pipeline writes its final decision straight back onto the
`Item` row (`approval_status`, `rejection_reason`, `metadata`).

`metadata` (already a JSONField on `Item`) stores per-attempt bookkeeping:

    {
      "moderation_state": "approved" | "rejected" | "needs_review" | "failed",
      "moderation_scores": {...},
      "moderation_reason": "...",
      "moderation_attempts": <int>,
      "moderation_error": "...",
      "moderation_decided_at": "<iso>",
      "needs_review": true    # set when the pipeline flags for human review
    }

The `needs_review` flag doubles as a "skip me" marker so the next drain
pass doesn't re-process items already routed to a human.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.utils import timezone

from DawaApp.models import Item

from .schemas import ModerationDecision, ModerationRow, ModerationStatus

logger = logging.getLogger(__name__)


def _merge_metadata(existing: Any, **updates: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    base.update(updates)
    return base


def load_pending_batch(limit: int) -> list[ModerationRow]:
    """Snapshot up to `limit` `Pending` items that still need auto-moderation.

    Items already routed to a human reviewer (`metadata.needs_review = true`)
    are excluded so we don't rescore them on every drain.
    """
    qs = (
        Item.objects.filter(approval_status="Pending")
        .exclude(metadata__needs_review=True)
        .select_related("seller")
        .prefetch_related("images")
        .order_by("created_at")[:limit]
    )

    rows: list[ModerationRow] = []
    for item in qs:
        image_urls = [img.image for img in item.images.all() if img.image]
        seller = getattr(item, "seller", None)
        rows.append(
            ModerationRow(
                item_id=item.id,
                seller_id=seller.id if seller else None,
                seller_email=(seller.email or None) if seller else None,
                title=item.item_name or "",
                description=item.item_description or "",
                image_urls=image_urls,
            )
        )
    return rows


def write_decision(item_id: int, decision: ModerationDecision) -> Optional[Item]:
    """Persist a pipeline decision back onto the `Item`.

    Mapping:
        APPROVED     -> approval_status='Approved', clear rejection_reason
        REJECTED     -> approval_status='Rejected', rejection_reason=<reason>
        NEEDS_REVIEW -> approval_status stays 'Pending', metadata.needs_review=True
        FAILED       -> approval_status stays 'Pending', metadata records error
    """
    try:
        item = Item.objects.get(pk=item_id)
    except Item.DoesNotExist:
        logger.warning("write_decision: item %s no longer exists", item_id)
        return None

    md_updates: dict[str, Any] = {
        "moderation_scores": decision.scores,
        "moderation_reason": decision.reason,
        "moderation_decided_at": timezone.now().isoformat(),
        "moderation_state": decision.status.value,
    }

    update_fields = ["metadata"]

    if decision.status is ModerationStatus.APPROVED:
        item.approval_status = "Approved"
        item.rejection_reason = None
        update_fields += ["approval_status", "rejection_reason"]
        item.metadata = _merge_metadata(item.metadata, **md_updates)
        # Clear the human-review marker if it was set on a previous pass.
        if isinstance(item.metadata, dict):
            item.metadata.pop("needs_review", None)

    elif decision.status is ModerationStatus.REJECTED:
        item.approval_status = "Rejected"
        item.rejection_reason = decision.reason or "policy violation"
        update_fields += ["approval_status", "rejection_reason"]
        item.metadata = _merge_metadata(item.metadata, **md_updates)

    elif decision.status is ModerationStatus.NEEDS_REVIEW:
        md_updates["needs_review"] = True
        item.metadata = _merge_metadata(item.metadata, **md_updates)

    else:  # FAILED — stays Pending, drain retries on the next pass
        current_attempts = 0
        if isinstance(item.metadata, dict):
            current_attempts = int(item.metadata.get("moderation_attempts") or 0)
        md_updates["moderation_attempts"] = current_attempts + 1
        md_updates["moderation_error"] = decision.reason or "unknown"
        item.metadata = _merge_metadata(item.metadata, **md_updates)

    if "updated_at" not in update_fields:
        update_fields.append("updated_at")
    item.save(update_fields=update_fields)
    return item


def mark_failed(item_id: int, error: str) -> None:
    """Convenience wrapper for transient errors from the pipeline."""
    write_decision(
        item_id,
        ModerationDecision(status=ModerationStatus.FAILED, reason=error[:2000]),
    )


def load_bad_image_hashes() -> list[int]:
    """Return the known-bad perceptual-hash blocklist.

    Currently a no-op — Dawa doesn't yet maintain a hash blocklist table.
    Kept as a symbol so the pipeline signature is stable; add a
    `BadImageHash` model + migration later and read from it here.
    """
    return []


