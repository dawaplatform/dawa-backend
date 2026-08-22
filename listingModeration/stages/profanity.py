"""Tier 4: local profanity check via `better-profanity`.

Aho-Corasick lookup — microseconds per call, no ML wheels, no network. Runs
before Gemini so obvious garbage is rejected without spending an API call
or risking a 429. If the wheel isn't installed on a given deploy, `score()`
returns None and the pipeline simply skips this tier instead of erroring.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Swahili / Luganda insults common on East-African marketplaces. Extends the
# library's default English list via `add_censor_words`.
_EXTRA_WORDS: tuple[str, ...] = (
    "malaya", "mshenzi", "punda", "mjinga", "kumamako", "mavi", "shoga",
)

_loaded = False
_check_fn = None  # (text: str) -> bool


def ensure_loaded() -> None:
    """Import + prime `better-profanity` once per process."""
    global _loaded, _check_fn
    if _loaded:
        return
    _loaded = True
    try:
        from better_profanity import profanity as _bp

        _bp.load_censor_words()
        _bp.add_censor_words(list(_EXTRA_WORDS))
        _check_fn = _bp.contains_profanity
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.info("better-profanity unavailable; skipping profanity tier: %s", exc)
        _check_fn = None


def score(title: str, description: str) -> Optional[float]:
    """Return 1.0 when profanity is detected, 0.0 when clean, None if unavailable.

    Kept as a float so the pipeline threshold config
    (`MODERATION_PROFANITY_REJECT`) still applies uniformly across all
    stages. `better-profanity` is a binary matcher so scores are always 0
    or 1 — any threshold in `(0.0, 1.0]` will trigger a reject on a hit.
    """
    ensure_loaded()
    if _check_fn is None:
        return None
    text = f"{title} {description or ''}".strip()
    if not text:
        return 0.0
    try:
        return 1.0 if _check_fn(text) else 0.0
    except Exception as exc:
        logger.warning("profanity scoring failed: %s", exc)
        return None

