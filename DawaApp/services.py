import os
import re
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Alias, so we auto-upgrade when Google ships a new Flash-Lite without a code change.
# Pinned alternatives (as of 2026-08): gemini-3.5-flash-lite, gemini-2.5-flash-lite,
# gemini-3.6-flash. See https://ai.google.dev/gemini-api/docs/models
DEFAULT_GEMINI_MODEL = "gemini-flash-lite-latest"

# When True, any message we cannot positively confirm as safe is treated as UNSAFE.
# This matches the product rule: "only moved on if is_safe is true; otherwise deleted".
SAFETY_FAIL_CLOSED = str(
    os.environ.get("MESSAGE_SAFETY_FAIL_CLOSED",
                   getattr(settings, "MESSAGE_SAFETY_FAIL_CLOSED", "true"))
).lower() in ("1", "true", "yes", "on")

# ---------------------------------------------------------------------------
# Layer 1 — local, offline prescreen (free, instant, no API calls)
# ---------------------------------------------------------------------------
# Catches the obvious cases so we don't burn Gemini quota (5 RPM on free tier)
# on things any keyword filter can flag. Profanity detection is delegated to
# `better-profanity` (Aho-Corasick, microseconds per check, ~4k built-in
# English words) plus a short local extension for common Swahili / Luganda
# insults. Scam / off-platform payment / harassment patterns stay as regex.

# Swahili / Luganda insults common on East-African marketplaces. Extends the
# library's default English list. Kept in code (not the DB) because these
# are policy, not data.
_EXTRA_PROFANITY_WORDS: tuple[str, ...] = (
    "malaya", "mshenzi", "punda", "mjinga", "kumamako", "mavi", "shoga",
)

_BETTER_PROFANITY_READY = False
_better_profanity_check = None  # callable(text) -> bool


def _ensure_better_profanity() -> None:
    """Import + prime `better-profanity` once per process.

    Best-effort: if the wheel isn't installed we log once and fall back to
    "no profanity signal from the local layer" — the AI layer still runs.
    """
    global _BETTER_PROFANITY_READY, _better_profanity_check
    if _BETTER_PROFANITY_READY:
        return
    _BETTER_PROFANITY_READY = True  # set first so we don't retry every call
    try:
        from better_profanity import profanity as _bp

        _bp.load_censor_words()
        _bp.add_censor_words(list(_EXTRA_PROFANITY_WORDS))
        _better_profanity_check = _bp.contains_profanity
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.info("better-profanity unavailable; local profanity tier disabled: %s", exc)
        _better_profanity_check = None


# Regex patterns for scams / off-platform payment / harassment.
# Anything matching here is treated as unsafe by the local prescreen.
_LOCAL_SCAM_PATTERNS = [
    # Direct payment-outside-platform requests
    re.compile(r"\b(send|transfer|deposit|pay)\b.{0,40}\b(mobile\s*money|momo|mtn|airtel|western\s*union|bank|account)\b", re.I),
    re.compile(r"\b(mobile\s*money|momo|mtn|airtel)\s*(number|no\.?|line)\b", re.I),
    # OTP / verification-code phishing
    re.compile(r"\b(otp|verification\s*code|one[-\s]*time\s*password|pin\s*code)\b", re.I),
    # Off-platform contact push (WhatsApp/Telegram) — soft signal, only combined with "outside" hints
    re.compile(r"\b(whats?app|telegram)\b.{0,40}\b(outside|off|private|instead)\b", re.I),
    # Threats
    re.compile(r"\b(i\s*will|i'?ll|nita|nakupa)\b.{0,20}\b(kill|beat|hurt|kula|piga|maliza)\b", re.I),
    # Explicit solicitation
    re.compile(r"\b(send|share)\b.{0,15}\b(nudes?|naked\s*pic|sex)\b", re.I),
    # 419 / advance-fee scams (classic "I have a business proposal for you")
    re.compile(r"\bbusiness\s+proposal\b", re.I),
    re.compile(r"\b(next\s+of\s+kin|inheritance|late\s+(husband|father|uncle)|deceased\s+(husband|father))\b", re.I),
    re.compile(r"\b(barrister|reverend|prince|sheikh)\b.{0,30}\b(from|of)\b.{0,20}\b(nigeria|sudan|ghana|liberia|syria)\b", re.I),
    # Romance / dating-bait scams
    re.compile(r"\b(soulmate|soul\s*mate)\b", re.I),
    re.compile(r"\b(single\s+and\s+searching|looking\s+for\s+(love|a\s+(man|woman|partner)))\b", re.I),
    re.compile(r"\b(write|contact|reach|email)\s+me\b.{0,20}\b(on\s+my\s+)?(email|gmail|yahoo|hotmail)\b", re.I),
    # Contacting off-platform via email addresses embedded in the body
    re.compile(r"\bmy\s+(email|e-mail)\s+(is|address\s+is|:)\b", re.I),
    re.compile(r"\b[a-z0-9._%+-]+@(gmail|yahoo|hotmail|outlook|aol)\.[a-z]{2,}\b", re.I),
]


def local_prescreen(text: str) -> dict:
    """
    Fast local safety check. No network, no cost.

    Returns {"is_safe": bool, "reason": str, "matched": bool}.
    - matched=True  → the local filter made a decision (unsafe).
    - matched=False → local check is clean, but caller should still run the AI check.
    """
    body = (text or "").strip()
    if not body:
        return {"is_safe": False, "reason": "Empty message body.", "matched": True}

    # Fast profanity check via better-profanity (Aho-Corasick).
    _ensure_better_profanity()
    if _better_profanity_check is not None:
        try:
            if _better_profanity_check(body):
                return {
                    "is_safe": False,
                    "reason": "Message contains profanity or an offensive term.",
                    "matched": True,
                }
        except Exception as exc:
            logger.warning("better-profanity check failed: %s", exc)

    for pattern in _LOCAL_SCAM_PATTERNS:
        m = pattern.search(body)
        if m:
            return {
                "is_safe": False,
                "reason": f"Local filter matched scam/abuse pattern: {m.group(0)!r}.",
                "matched": True,
            }

    return {"is_safe": True, "reason": "Local prescreen clean.", "matched": False}


SAFETY_PROMPT_TEMPLATE = """
You are a content moderation assistant for an online marketplace called Dawa.
Your job is to evaluate whether a message sent between a buyer and a seller is safe and appropriate.

A message is UNSAFE if it contains any of the following:
- Hate speech, discrimination, or harassment targeting individuals or groups
- Threats of violence or physical harm
- Explicit sexual content or solicitation
- Scam, phishing, or fraud attempts (e.g. asking for payment outside the platform, fake deals)
- Personal attacks or severe verbal abuse
- Promotion of illegal activities

A message is SAFE if it is a normal marketplace conversation, such as:
- Asking about product availability, price, or condition
- Negotiating a price or delivery
- Sharing contact details for legitimate transaction purposes
- General polite conversation related to a purchase or sale

Respond ONLY with a valid JSON object in this exact format (no extra text):
{{
  "is_safe": true or false,
  "reason": "one-sentence explanation"
}}

Message to evaluate:
\"\"\"{message}\"\"\"
"""

BATCH_SAFETY_PROMPT_TEMPLATE = """
You are a content moderation assistant for an online marketplace called Dawa.
Evaluate each message below for safety.

A message is UNSAFE if it contains any of the following:
- Hate speech, discrimination, or harassment targeting individuals or groups
- Threats of violence or physical harm
- Explicit sexual content or solicitation
- Scam, phishing, or fraud attempts (e.g. asking for payment outside the platform, fake deals)
- Personal attacks or severe verbal abuse
- Promotion of illegal activities

A message is SAFE if it is normal marketplace conversation (price queries, delivery, general chat about a product, etc.).

Respond ONLY with a JSON array — one entry per message in the same order — with this exact shape:
[
  {{"id": <message_id>, "is_safe": true or false, "reason": "one-sentence explanation"}},
  ...
]

Messages:
{messages_json}
"""


def _get_key_and_model() -> tuple[str, str]:
    """Return (api_key, model_name) or raise ValueError."""
    api_key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or getattr(settings, "GEMINI_API_KEY", None)
    )
    if not api_key:
        raise ValueError("GEMINI_API_KEY not configured.")
    api_key = api_key.strip()

    model_name = (
        os.environ.get("GEMINI_MODEL")
        or getattr(settings, "GEMINI_MODEL", None)
        or DEFAULT_GEMINI_MODEL
    )
    return api_key, model_name


# REST endpoint per https://ai.google.dev/api/generate-content
_GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def _call_gemini_rest(prompt: str, *, max_output_tokens: int, timeout: float = 30.0) -> str:
    """Call generateContent via plain REST and return the response text.

    Bypasses the google-genai SDK, which has httpx transport bugs that
    manifest as instant '_ssl.c:983: handshake operation timed out' errors
    even when the network is fine. Plain requests is more predictable.
    """
    import requests  # deferred import — requests is already in requirements.txt

    api_key, model_name = _get_key_and_model()
    url = _GEMINI_URL_TEMPLATE.format(model=model_name)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
        },
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    resp = requests.post(url, json=body, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise RuntimeError(f"Prompt blocked by Gemini: {block}")
        raise RuntimeError(f"No candidates returned: {str(data)[:200]}")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        raise RuntimeError(f"Empty response text: {str(data)[:200]}")
    return text


def _extract_json(raw: str) -> str:
    """Strip markdown fences and leading prose so json.loads gets clean input."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


def _uncertain(reason: str) -> dict:
    """Result to return when we could not positively verify safety.

    Honors SAFETY_FAIL_CLOSED: True => treat uncertain as unsafe (reject);
    False => legacy fail-open behavior.
    """
    return {"is_safe": (not SAFETY_FAIL_CLOSED), "reason": reason}


def check_message_safety(message_text: str) -> dict:
    """
    Check a single message for safety using Gemini AI (plain REST).

    Returns {"is_safe": bool, "reason": str}.
    Fails CLOSED by default (SAFETY_FAIL_CLOSED=True).
    """
    prompt = SAFETY_PROMPT_TEMPLATE.format(message=message_text)
    raw_text = ""
    try:
        raw_text = _extract_json(_call_gemini_rest(prompt, max_output_tokens=512, timeout=30))
        if not raw_text.startswith("{"):
            start, end = raw_text.find("{"), raw_text.rfind("}") + 1
            if start != -1 and end > start:
                raw_text = raw_text[start:end]

        result = json.loads(raw_text)
        is_safe = bool(result.get("is_safe", True))
        reason = str(result.get("reason", ""))
        logger.info(
            "Safety check | safe=%s | reason=%s | preview=%.60s",
            is_safe, reason, message_text,
        )
        return {"is_safe": is_safe, "reason": reason}

    except ValueError as exc:
        logger.warning("Safety check unavailable: %s", exc)
        return _uncertain(f"Safety check unavailable: {exc}")
    except json.JSONDecodeError as exc:
        logger.error("Safety check JSON parse error: %s | raw=%s", exc, raw_text)
        return _uncertain("Safety check inconclusive (parse error).")
    except Exception as exc:
        logger.error("Safety check failed: %s", exc)
        return _uncertain("Safety check skipped due to service error.")


def check_messages_batch(messages: list[dict]) -> list[dict]:
    """
    Check multiple messages in a single Gemini API call (plain REST).

    Args:
        messages: list of {"id": int, "text": str}

    Returns:
        list of {"id": int, "is_safe": bool, "reason": str}
        On complete API failure, returns is_safe=True with reason starting
        "API_ERROR:" so callers can distinguish "AI couldn't decide" from
        "we never reached the AI" (important for --strict purges).
    """
    if not messages:
        return []

    fallback = {m["id"]: {"id": m["id"], "is_safe": True, "reason": "Skipped."} for m in messages}

    def api_error_fallback(reason: str) -> list[dict]:
        return [
            {"id": m["id"], "is_safe": True, "reason": f"API_ERROR: {reason}"}
            for m in messages
        ]

    messages_json = json.dumps(
        [{"id": m["id"], "text": (m["text"] or "")[:500]} for m in messages],
        ensure_ascii=False,
        indent=2,
    )
    prompt = BATCH_SAFETY_PROMPT_TEMPLATE.format(messages_json=messages_json)

    raw_text = ""
    try:
        raw_text = _extract_json(_call_gemini_rest(prompt, max_output_tokens=1024, timeout=60))
        if not raw_text.startswith("["):
            start, end = raw_text.find("["), raw_text.rfind("]") + 1
            if start != -1 and end > start:
                raw_text = raw_text[start:end]

        results = json.loads(raw_text)
        output = []
        for item in results:
            msg_id = item.get("id")
            if msg_id is None:
                continue
            output.append({
                "id": msg_id,
                "is_safe": bool(item.get("is_safe", True)),
                "reason": str(item.get("reason", "")),
            })

        returned_ids = {r["id"] for r in output}
        for m in messages:
            if m["id"] not in returned_ids:
                output.append(fallback[m["id"]])

        logger.info("Batch safety check | checked=%d", len(output))
        return output

    except ValueError as exc:
        logger.warning("Batch safety check unavailable: %s", exc)
        return api_error_fallback(str(exc))
    except json.JSONDecodeError as exc:
        logger.error("Batch safety check JSON parse error: %s | raw=%.200s", exc, raw_text)
        return api_error_fallback(f"parse error: {exc}")
    except Exception as exc:
        logger.error("Batch safety check failed: %s", exc)
        return api_error_fallback(str(exc))


# ---------------------------------------------------------------------------
# Public entry point — use this from views / signals / commands
# ---------------------------------------------------------------------------
def moderate_message(message_text: str, *, use_ai: bool = True) -> dict:
    """
    Full moderation pipeline: local prescreen → (optional) Gemini deep check.

    Args:
        message_text: raw message body.
        use_ai: when False, only the local prescreen runs (no API call).
                Use False in hot paths / signals where every insert must be
                cheap. Use True in the send-message view.

    Returns {"is_safe": bool, "reason": str, "layer": "local"|"ai"|"none"}.

    Fails CLOSED per SAFETY_FAIL_CLOSED.
    """
    local = local_prescreen(message_text)
    if local["matched"]:
        return {"is_safe": local["is_safe"], "reason": local["reason"], "layer": "local"}

    if not use_ai:
        return {"is_safe": True, "reason": "Local prescreen clean.", "layer": "local"}

    ai = check_message_safety(message_text)
    return {"is_safe": ai["is_safe"], "reason": ai["reason"], "layer": "ai"}

