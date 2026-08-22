"""Policy knobs for listing moderation.

Env-var first, Django settings second — so `DEBUG` toggles from `.env` still
work without a redeploy, while ops can override at deploy time by exporting
`MODERATION_*`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _read(name: str, default=None):
    """Return env var if set, else `django.conf.settings.<name>`, else default."""
    value = os.getenv(name)
    if value is not None:
        return value
    try:
        from django.conf import settings
        return getattr(settings, name, default)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_read(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_read(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _read(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ModerationConfig:
    batch_size: int = _env_int("MODERATION_BATCH_SIZE", 5)

    text_reject_threshold: float = _env_float("MODERATION_TEXT_REJECT", 0.85)
    text_review_threshold: float = _env_float("MODERATION_TEXT_REVIEW", 0.50)
    image_reject_threshold: float = _env_float("MODERATION_IMAGE_REJECT", 0.90)
    image_review_threshold: float = _env_float("MODERATION_IMAGE_REVIEW", 0.60)

    phash_distance_threshold: int = _env_int("MODERATION_PHASH_DISTANCE", 5)

    # Tier 4: local profanity check via better-profanity (Aho-Corasick, no ML).
    enable_profanity_check: bool = _env_bool("MODERATION_ENABLE_PROFANITY_CHECK", True)
    profanity_reject_threshold: float = _env_float("MODERATION_PROFANITY_REJECT", 0.90)

    # Tier 5+6: Gemini text + vision. Auto-skipped when GEMINI_API_KEY is unset.
    enable_gemini: bool = _env_bool("MODERATION_ENABLE_GEMINI", True)
    gemini_max_retries: int = _env_int("MODERATION_GEMINI_MAX_RETRIES", 2)
    gemini_retry_base_delay: float = _env_float("MODERATION_GEMINI_RETRY_BASE_DELAY", 1.5)

    # Tier 7: OpenAI omni-moderation failover (free tier, only when Gemini fails).
    enable_openai_free_api: bool = _env_bool("MODERATION_ENABLE_OPENAI_FREE_API", True)
    openai_moderation_model: str = str(
        _read("MODERATION_OPENAI_MODEL", "omni-moderation-latest") or "omni-moderation-latest"
    )

    notify_merchant_on_decision: bool = _env_bool("MODERATION_NOTIFY_MERCHANT", True)
    notify_merchant_on_approved: bool = _env_bool("MODERATION_NOTIFY_ON_APPROVED", True)

    max_images_per_listing: int = _env_int("MODERATION_MAX_IMAGES", 8)
    image_download_timeout_seconds: float = _env_float("MODERATION_IMAGE_DOWNLOAD_TIMEOUT", 8.0)
    max_image_bytes: int = _env_int("MODERATION_MAX_IMAGE_BYTES", 5 * 1024 * 1024)

    # When both Gemini AND the OpenAI failover come back with no score AND
    # the cheap checks were clean, auto-approve instead of parking in review
    # forever. Recommended True in prod.
    fail_open_when_model_unavailable: bool = _env_bool(
        "MODERATION_FAIL_OPEN_WHEN_MODEL_UNAVAILABLE", True,
    )

    @property
    def gemini_api_key(self) -> str:
        return str(_read("GEMINI_API_KEY") or _read("GOOGLE_API_KEY") or "")

    @property
    def gemini_model(self) -> str:
        return str(_read("GEMINI_MODEL", "gemini-flash-lite-latest") or "gemini-flash-lite-latest")

    @property
    def openai_api_key(self) -> str:
        return str(_read("OPENAI_API_KEY", "") or "")


# Deny-list is intentionally short here; extend from your real policy doc.
# Kept in code (not the DB) because these are policy, not data — they should
# be reviewed in PRs, not by SQL edits.
BANNED_KEYWORDS: frozenset[str] = frozenset({
    "counterfeit",
    "replica",
    "fake rolex",
    "stolen",
    "child porn",
    "cp for sale",
    "human trafficking",
    "escort service",
    "meth",
    "cocaine for sale",
    "gun for sale",
    "ak-47 for sale",
})


config = ModerationConfig()

