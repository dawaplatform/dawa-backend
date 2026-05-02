"""
Rate limits for sensitive endpoints. Uses DRF SimpleRateThrottle (per-IP by default).
"""
from rest_framework.throttling import SimpleRateThrottle


class AuthEndpointThrottle(SimpleRateThrottle):
    """
    Throttle brute-force attempts on auth-related POST endpoints (shared per IP).
    Rate is configured via REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['auth'].
    """

    scope = 'auth'
