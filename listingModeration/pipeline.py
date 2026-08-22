"""Moderation pipeline — cheapest checks first, short-circuit on any hit.

Order:
    1. Banned-keyword check on title/description       (microseconds)
    2. Perceptual-hash blocklist                       (network I/O)
    3. Image metadata / provenance inspection          (Pillow only)
    4. Local profanity check (better-profanity)        (CPU)
    5. Gemini text moderation                          (~1-3s)
    6. Gemini image moderation                         (~1-3s per image)
    7. OpenAI omni-moderation failover                 (only when Gemini fails)
    8. Threshold-based decision -> approved / rejected / needs_review

Async because stages 5-7 hit the network; run via `asyncio.run(...)` from
the `moderate_listings` management command.
"""
from __future__ import annotations

import logging
from typing import Any

from . import service
from .config import config
from .schemas import ModerationDecision, ModerationRow, ModerationStatus
from .stages import (
    image_moderation,
    keywords,
    metadata,
    openai_moderation,
    phash,
    profanity,
    text_moderation,
)


logger = logging.getLogger(__name__)


def _decide_from_scores(text_score: float | None, image_score: float | None) -> tuple[ModerationStatus, str | None]:
    # Unknown scores from BOTH providers. Fall back to the cheap-checks
    # verdict per config.fail_open_when_model_unavailable.
    if text_score is None or image_score is None:
        if config.fail_open_when_model_unavailable:
            return (
                ModerationStatus.APPROVED,
                "auto-approved: moderation models unavailable, cheap checks clean",
            )
        return ModerationStatus.NEEDS_REVIEW, "moderation models unavailable — manual review required"

    if text_score >= config.text_reject_threshold:
        return ModerationStatus.REJECTED, f"text policy score {text_score:.2f} exceeds reject threshold"
    if image_score >= config.image_reject_threshold:
        return ModerationStatus.REJECTED, f"image policy score {image_score:.2f} exceeds reject threshold"

    if text_score >= config.text_review_threshold:
        return ModerationStatus.NEEDS_REVIEW, f"text policy score {text_score:.2f} in ambiguous range"
    if image_score >= config.image_review_threshold:
        return ModerationStatus.NEEDS_REVIEW, f"image policy score {image_score:.2f} in ambiguous range"

    return ModerationStatus.APPROVED, None


async def moderate(row: ModerationRow, known_bad_hashes: list[int]) -> ModerationDecision:
    scores: dict[str, Any] = {}
    logger.info(
        "[Moderation] start item=%s title=%r images=%d",
        row.item_id, row.title[:80], len(row.image_urls),
    )

    # Stage 1: keyword deny-list.
    hit = keywords.check(row.title, row.description)
    if hit:
        logger.warning("[Moderation][keywords] REJECT item=%s match=%r", row.item_id, hit)
        return ModerationDecision(
            status=ModerationStatus.REJECTED,
            reason=f"banned keyword matched: '{hit}'",
            scores={"stage": "keywords", "match": hit},
        )

    # Stage 2: pHash blocklist. Downloads bytes we reuse in stages 3 & 6.
    phash_reason, image_cache = await phash.check(row.image_urls, known_bad_hashes)
    if phash_reason:
        logger.warning("[Moderation][phash] REJECT item=%s reason=%s", row.item_id, phash_reason)
        return ModerationDecision(
            status=ModerationStatus.REJECTED,
            reason=phash_reason,
            scores={"stage": "phash"},
        )

    # Stage 3: image metadata inspection (foreign URLs, AI-generator markers).
    for url, _phash_val, data in image_cache:
        if not data:
            continue
        meta_reason = metadata.check(data, url=url)
        if meta_reason:
            logger.warning("[Moderation][metadata] REJECT item=%s url=%s reason=%s",
                           row.item_id, url, meta_reason)
            return ModerationDecision(
                status=ModerationStatus.REJECTED,
                reason=f"{meta_reason} (url={url})",
                scores={"stage": "metadata", "url": url},
            )

    # Stage 4: local profanity (better-profanity).
    if config.enable_profanity_check:
        prof = profanity.score(row.title, row.description)
        if prof is not None:
            scores["profanity"] = prof
            if prof >= config.profanity_reject_threshold:
                logger.warning("[Moderation][profanity] REJECT item=%s score=%.2f",
                               row.item_id, prof)
                return ModerationDecision(
                    status=ModerationStatus.REJECTED,
                    reason="profanity detected in title or description",
                    scores={"stage": "profanity", "profanity": prof},
                )

    # Stage 5+6: Gemini text + vision (only if configured & enabled).
    text_score: float | None = None
    image_score: float | None = None
    if config.enable_gemini and config.gemini_api_key:
        text_result = await text_moderation.check(row.title, row.description)
        scores["text"] = text_result
        image_result = await image_moderation.check(image_cache)
        scores["image"] = image_result
        text_score = text_result.get("max_score")
        image_score = image_result.get("max_score")
    else:
        logger.info("[Moderation] item=%s Gemini disabled/unconfigured; skipping to failover",
                    row.item_id)

    # Stage 7: OpenAI omni-moderation failover when Gemini couldn't score.
    if (text_score is None or image_score is None) and config.enable_openai_free_api:
        oai = await openai_moderation.check(row.title, row.description, row.image_urls)
        scores["openai"] = oai
        if oai.get("flagged"):
            cats = ", ".join(oai.get("categories") or []) or "policy violation"
            logger.warning("[Moderation][openai] REJECT item=%s categories=%s",
                           row.item_id, cats)
            return ModerationDecision(
                status=ModerationStatus.REJECTED,
                reason=f"openai moderation flagged: {cats}",
                scores=scores,
            )
        oai_score = oai.get("max_score")
        if oai_score is not None:
            if text_score is None:
                text_score = oai_score
            if image_score is None:
                image_score = oai_score

    status, reason = _decide_from_scores(text_score, image_score)
    logger.info(
        "[Moderation] item=%s DECISION=%s reason=%s scores=%s",
        row.item_id, status.value.upper(), reason or "clean", scores,
    )
    return ModerationDecision(status=status, reason=reason, scores=scores)


async def process_batch(batch_size: int) -> dict[str, int]:
    """Drain up to `batch_size` pending Items. Returns per-status counts."""
    from . import notifications

    rows = service.load_pending_batch(batch_size)
    counts = {
        "processed": 0,
        "approved": 0,
        "rejected": 0,
        "needs_review": 0,
        "failed": 0,
    }
    if not rows:
        return counts

    logger.info("[Moderation] draining %d item(s)", len(rows))
    known_bad_hashes = service.load_bad_image_hashes()

    for row in rows:
        counts["processed"] += 1
        try:
            decision = await moderate(row, known_bad_hashes)
            service.write_decision(row.item_id, decision)
            try:
                notifications.notify_decision(row, decision)
            except Exception as exc:
                logger.warning("notification failed for item %s: %s", row.item_id, exc)
            counts[decision.status.value] = counts.get(decision.status.value, 0) + 1
        except Exception as exc:
            logger.exception("[Moderation] pipeline crashed for item %s", row.item_id)
            service.mark_failed(row.item_id, repr(exc))
            counts["failed"] += 1

    logger.info("[Moderation] drain done: %s", counts)
    return counts


