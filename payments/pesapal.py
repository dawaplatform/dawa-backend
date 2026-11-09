"""Thin client for Pesapal API 3.0 (https://developer.pesapal.com)."""
import requests
from django.conf import settings
from django.core.cache import cache

TIMEOUT = 30
TOKEN_CACHE_KEY = "pesapal:token"
# Tokens live 5 minutes; refresh a bit early.
TOKEN_TTL_SECONDS = 240


class PesapalError(Exception):
    pass


def _url(path: str) -> str:
    return f"{settings.PESAPAL_API_URL.rstrip('/')}/api/{path}"


def _check(data: dict) -> dict:
    error = data.get("error") if isinstance(data, dict) else None
    if error and (error.get("message") or error.get("code")):
        raise PesapalError(f"{error.get('code')}: {error.get('message')}")
    return data


def get_token(force_refresh: bool = False) -> str:
    if not force_refresh:
        token = cache.get(TOKEN_CACHE_KEY)
        if token:
            return token
    if not settings.PESAPAL_CONSUMER_KEY or not settings.PESAPAL_CONSUMER_SECRET:
        raise PesapalError("Pesapal consumer key/secret are not configured.")
    resp = requests.post(
        _url("Auth/RequestToken"),
        json={
            "consumer_key": settings.PESAPAL_CONSUMER_KEY,
            "consumer_secret": settings.PESAPAL_CONSUMER_SECRET,
        },
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = _check(resp.json())
    token = data.get("token")
    if not token:
        raise PesapalError(f"No token returned: {data}")
    cache.set(TOKEN_CACHE_KEY, token, TOKEN_TTL_SECONDS)
    return token


def _request(method: str, path: str, **kwargs) -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_token()}",
    }
    resp = requests.request(method, _url(path), headers=headers, timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    return _check(resp.json())


def register_ipn(url: str, notification_type: str = "GET") -> dict:
    return _request("POST", "URLSetup/RegisterIPN", json={"url": url, "ipn_notification_type": notification_type})


def get_ipn_list() -> list:
    return _request("GET", "URLSetup/GetIpnList")


def submit_order(payload: dict) -> dict:
    return _request("POST", "Transactions/SubmitOrderRequest", json=payload)


def get_transaction_status(order_tracking_id: str) -> dict:
    return _request("GET", "Transactions/GetTransactionStatus", params={"orderTrackingId": order_tracking_id})
