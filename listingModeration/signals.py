"""Auto-fire the moderation pipeline when a listing is posted or edited.

Subscribes to `post_save` on `DawaApp.Item` and runs the async pipeline in a
short-lived daemon thread. The management command (`moderate_listings`) is
still available as a safety net / for bulk re-scan, but no longer required
for normal seller traffic.

Key guarantees:

* One save event -> one background pass. We short-circuit on:
    - approval_status != 'Pending'  (Approved / Rejected — nothing to do)
    - metadata.needs_review == True (already routed to a human)
    - metadata.moderation_state in {'processing', 'failed', 'needs_review'}
    - metadata.skip_auto_moderation == True (bulk imports / seed scripts)

* We never re-enter the pipeline from our own write-back. `write_decision`
  flips the item into a terminal state before saving, which trips the skip
  check on the next `post_save`.

* `AddItem` inserts the `Item` row BEFORE it uploads images to Cloudinary,
  so the receiver waits a few seconds before snapshotting to make sure the
  images are on the row when the pipeline reads it.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Optional

from django.db import close_old_connections, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from DawaApp.models import Item

logger = logging.getLogger(__name__)

# `AddItem` uploads each image to Cloudinary synchronously (~0.5-2s each).
# Wait long enough for a typical 3-5 image listing before we snapshot.
_CREATED_DELAY_SECONDS = 6.0
_UPDATED_DELAY_SECONDS = 5.0
_STATE_KEY = "moderation_state"
_STATE_PROCESSING = "processing"


def _should_skip(item: Item) -> bool:
    if item.approval_status != "Pending":
        return True
    md = item.metadata if isinstance(item.metadata, dict) else {}
    if md.get("skip_auto_moderation"):
        return True
    if md.get("needs_review") is True:
        return True
    if md.get(_STATE_KEY) in {"processing", "failed", "needs_review", "approved", "rejected"}:
        # 'processing' -> another thread is on it.
        # 'failed'     -> transient error, drain command retries.
        # terminal     -> a race we ignore; next edit resets the state.
        return True
    return False


def _mark_processing(item_id: int) -> bool:
    """Set `metadata.moderation_state='processing'` via `.update()` (no signal).

    Returns True when we claimed the row, False if someone else already did.
    """
    try:
        item = Item.objects.only("metadata").get(pk=item_id)
    except Item.DoesNotExist:
        return False
    md = dict(item.metadata) if isinstance(item.metadata, dict) else {}
    if md.get(_STATE_KEY) == _STATE_PROCESSING:
        return False
    md[_STATE_KEY] = _STATE_PROCESSING
    Item.objects.filter(pk=item_id).update(metadata=md)
    return True


def _run_pipeline(item_id: int, delay: float) -> None:
    """Background thread body: sleep briefly, then run the async pipeline."""
    if delay > 0:
        time.sleep(delay)

    try:
        from . import notifications, service
        from .pipeline import moderate

        row = service.load_row_for_item(item_id)
        if row is None:
            logger.info("auto-moderation: item %s not pending; skipping", item_id)
            return

        if not _mark_processing(item_id):
            logger.info("auto-moderation: item %s already claimed; skipping", item_id)
            return

        known_bad = service.load_bad_image_hashes()
        try:
            decision = asyncio.run(moderate(row, known_bad))
        except Exception as exc:
            logger.exception("auto-moderation: pipeline crashed for item %s", item_id)
            service.mark_failed(item_id, repr(exc))
            return

        service.write_decision(item_id, decision)
        try:
            notifications.notify_decision(row, decision)
        except Exception as exc:
            logger.warning(
                "auto-moderation: notification failed for item %s: %s", item_id, exc
            )
        logger.info(
            "auto-moderation: item %s -> %s", item_id, decision.status.value.upper()
        )
    except Exception:
        logger.exception("auto-moderation: unexpected error for item %s", item_id)
    finally:
        # Long-lived worker threads must close their own DB connections.
        close_old_connections()


def _schedule(item_id: int, delay: float) -> None:
    threading.Thread(
        target=_run_pipeline,
        args=(item_id, delay),
        name=f"moderation-item-{item_id}",
        daemon=True,
    ).start()


@receiver(post_save, sender=Item, dispatch_uid="listingModeration.on_item_saved")
def on_item_saved(sender, instance: Item, created: bool, **kwargs: Any) -> None:
    if _should_skip(instance):
        return

    item_id = instance.pk
    delay = _CREATED_DELAY_SECONDS if created else _UPDATED_DELAY_SECONDS

    def _fire() -> None:
        _schedule(item_id, delay)

    # Fires immediately when no atomic block is active, or right after the
    # outer transaction commits — either way the thread runs off the request path.
    transaction.on_commit(_fire)
