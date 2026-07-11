import os
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

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


def check_message_safety(message_text: str) -> dict:
    """
    Check whether a message is safe to deliver using Gemini AI.

    Returns a dict:
        {
            "is_safe": bool,   # True = safe to deliver, False = blocked
            "reason": str      # short explanation
        }

    On any error the function fails-open (returns is_safe=True) so that a
    temporary API outage never silently blocks legitimate messages. All
    errors are logged for visibility.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", None)

    if not api_key:
        logger.warning("GEMINI_API_KEY not configured – skipping safety check.")
        return {"is_safe": True, "reason": "Safety check skipped: API key not configured."}

    raw_text = ""
    try:
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.error(
                "google-genai package is not installed. "
                "Add 'google-genai' to requirements.txt and redeploy."
            )
            return {"is_safe": True, "reason": "Safety check skipped: google-genai not installed."}

        client = genai.Client(api_key=api_key)

        prompt = SAFETY_PROMPT_TEMPLATE.format(message=message_text)

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=256,
            ),
        )

        raw_text = response.text.strip()

        # Strip markdown code fences if Gemini wrapped the JSON
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        result = json.loads(raw_text)

        is_safe = bool(result.get("is_safe", True))
        reason = str(result.get("reason", ""))

        logger.info(
            "Safety check | safe=%s | reason=%s | message_preview=%.60s",
            is_safe,
            reason,
            message_text,
        )

        return {"is_safe": is_safe, "reason": reason}

    except json.JSONDecodeError as exc:
        logger.error("Safety check JSON parse error: %s | raw=%s", exc, raw_text)
        return {"is_safe": True, "reason": "Safety check inconclusive (parse error)."}

    except Exception as exc:
        logger.error("Safety check failed with unexpected error: %s", exc)
        return {"is_safe": True, "reason": "Safety check skipped due to service error."}
