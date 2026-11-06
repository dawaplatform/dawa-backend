"""Tunable weights for the home feed. Scores are on a 0-100ish scale."""

QUALITY_WEIGHT = 40.0
FRESHNESS_WEIGHT = 35.0
ENGAGEMENT_WEIGHT = 15.0
PROMOTED_BOOST = 8.0
LOCATION_BOOST = 10.0
REPORT_PENALTY = 15.0
# Random per-session nudge so refreshes don't always show the exact same order.
SESSION_JITTER = 4.0

BLOCK_SIZE = 20
SELLER_CAP_PER_BLOCK = 2
MAX_SAME_SUBCATEGORY_RUN = 3

NEW_BADGE_HOURS = 72
TRENDING_MIN_VIEWS = 5
TRENDING_MIN_ACTIONS = 1
TRENDING_TOP_SHARE = 0.10

RANKING_FETCH_LIMIT = 1000
SESSION_TTL_SECONDS = 30 * 60
PAGE_SIZE = 16
MAX_PAGE_SIZE = 60

PAID_PACKAGES = frozenset({"Boost 7", "Boost 30", "Essential Plan", "Growth Plan", "Elite Plan"})

FRESHNESS_BANDS: tuple[tuple[float, float], ...] = (
    (6, 100.0),
    (24, 90.0),
    (72, 75.0),
    (120, 60.0),
    (192, 45.0),
    (360, 30.0),
    (744, 15.0),
)
FRESHNESS_FLOOR = 5.0
