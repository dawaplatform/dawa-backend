"""
Rate limits for sensitive endpoints. Uses DRF SimpleRateThrottle (per-IP by default).

DRF 3.15 made get_cache_key() abstract on SimpleRateThrottle; subclasses must
implement it. We throttle every request (authenticated or not) by client IP
so that brute-force attempts from a single IP are blocked regardless of auth state.
"""
from rest_framework.throttling import SimpleRateThrottle


class AuthEndpointThrottle(SimpleRateThrottle):
    """
    Throttle brute-force attempts on auth-related POST endpoints (shared per IP).
    Rate is configured via REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['auth'].
    """

    scope = 'auth'

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident,
        }
