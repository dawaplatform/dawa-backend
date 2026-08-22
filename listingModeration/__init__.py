"""Listing moderation — auto-review pipeline for Dawa Items.

Pipeline (cheapest first, short-circuits on any hit):
    1. Banned-keyword deny-list          (regex, microseconds)
    2. Perceptual-hash blocklist         (Pillow-only aHash)
    3. Image metadata / provenance       (EXIF/XMP/PNG-text)
    4. Local profanity check             (better-profanity)
    5. Gemini text moderation            (~1-3s)
    6. Gemini image moderation           (~1-3s per image)
    7. OpenAI omni-moderation failover   (only if Gemini unavailable)

Trigger: `Item` rows created with `approval_status='Pending'` are drained
by `python manage.py moderate_listings` — schedule this from cron / a
systemd timer / your task runner. Decisions write back onto
`Item.approval_status` (+ `Item.rejection_reason` / `Item.metadata`).
"""

default_app_config = "listingModeration.apps.ListingModerationConfig"
