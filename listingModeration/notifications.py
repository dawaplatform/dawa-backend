"""Merchant email notifications for moderation decisions.

Best-effort: never raises into the pipeline. Uses Django's `EmailMessage`
against the SMTP backend already configured in `DawaProject.settings`.
Called synchronously — the drain runs offline in a management command, so
blocking here is fine.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMessage

from DawaApp.models import Item

from .config import config
from .schemas import ModerationDecision, ModerationRow, ModerationStatus

logger = logging.getLogger(__name__)

_STATUS_TO_LABEL = {
    ModerationStatus.APPROVED: "approved",
    ModerationStatus.REJECTED: "rejected",
    ModerationStatus.NEEDS_REVIEW: "needs_review",
}

_TEMPLATES: dict[str, tuple[str, str]] = {
    "approved": (
        "Your Dawa listing '{title}' is now live",
        (
            "Hello {name},\n\n"
            "Great news — your listing '{title}' passed our automated review "
            "and is now visible to buyers on Dawa.\n\n"
            "You can manage it anytime from your seller dashboard.\n\n"
            "— The Dawa Team"
        ),
    ),
    "rejected": (
        "Your Dawa listing '{title}' was not approved",
        (
            "Hello {name},\n\n"
            "Unfortunately your listing '{title}' did not pass our automated "
            "review and cannot be published as-is.\n\n"
            "Reason: {reason}\n\n"
            "You can edit the listing to address the issue and resubmit it, "
            "or contact support if you believe this was a mistake.\n\n"
            "— The Dawa Team"
        ),
    ),
    "needs_review": (
        "Your Dawa listing '{title}' is under manual review",
        (
            "Hello {name},\n\n"
            "Your listing '{title}' needs a human reviewer to take a second "
            "look before it can go live. We'll email you again with the "
            "final decision as soon as it's ready.\n\n"
            "Reason flagged: {reason}\n\n"
            "— The Dawa Team"
        ),
    ),
}


def _resolve_seller(row: ModerationRow) -> tuple[Optional[str], str]:
    """Return (email, display_name) for the row's seller."""
    email = row.seller_email
    name = ""

    if row.seller_id:
        try:
            user = User.objects.only("email", "first_name", "last_name").get(pk=row.seller_id)
            email = email or user.email
            name = (f"{user.first_name} {user.last_name}".strip() or user.email or "").strip()
        except User.DoesNotExist:
            pass

    if not email:
        # Fall back to looking the user up via the item's seller relation.
        try:
            item = Item.objects.select_related("seller").only(
                "seller__email", "seller__first_name", "seller__last_name",
            ).get(pk=row.item_id)
            if item.seller:
                email = item.seller.email
                name = (f"{item.seller.first_name} {item.seller.last_name}".strip()
                        or item.seller.email or "")
        except Item.DoesNotExist:
            pass

    return email, (name or "there")


def _send(email: str, name: str, product_title: str, label: str, reason: Optional[str]) -> None:
    subject_tpl, body_tpl = _TEMPLATES[label]
    subject = subject_tpl.format(title=product_title or "your listing")
    body = body_tpl.format(
        name=name,
        title=product_title or "your listing",
        reason=reason or "policy check",
    )
    try:
        EmailMessage(
            subject=subject,
            body=body,
            from_email=getattr(settings, "EMAIL_HOST_USER", None) or None,
            to=[email],
        ).send(fail_silently=True)
    except Exception as exc:
        logger.warning("decision email failed for %s: %s", email, exc)


def notify_decision(row: ModerationRow, decision: ModerationDecision) -> None:
    """Auto-pipeline path: email the merchant with the queue-row decision."""
    if not config.notify_merchant_on_decision:
        return
    label = _STATUS_TO_LABEL.get(decision.status)
    if label is None:
        return  # failed / processing — no email
    if label == "approved" and not config.notify_merchant_on_approved:
        return

    email, name = _resolve_seller(row)
    if not email:
        logger.info("no seller email for item %s; skipping decision email", row.item_id)
        return
    _send(email, name, row.title, label, decision.reason)


def notify_item_manual(
    item: Any,
    new_status: str,
    reason: Optional[str] = None,
) -> None:
    """Admin path: email the merchant when an admin manually decides an Item.

    Call this from your admin action after flipping `item.approval_status`.
    """
    if not config.notify_merchant_on_decision:
        return
    label = {"Approved": "approved", "Rejected": "rejected", "Pending": "needs_review"}.get(new_status)
    if label is None:
        return
    if label == "approved" and not config.notify_merchant_on_approved:
        return

    seller = getattr(item, "seller", None)
    if not seller or not seller.email:
        logger.info("no seller email for item %s; skipping manual decision email",
                    getattr(item, "id", "?"))
        return
    name = (f"{seller.first_name} {seller.last_name}".strip() or seller.email)
    _send(seller.email, name, getattr(item, "item_name", "your listing"), label, reason)

