import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from DawaApp.models import Item

from . import pesapal
from .config import BOOST_PACKAGES, CURRENCY
from .models import BoostPayment

# Pesapal status_code -> our status. 0 (INVALID) is also returned while the order is still unpaid.
STATUS_CODES = {1: BoostPayment.COMPLETED, 2: BoostPayment.FAILED, 3: BoostPayment.REVERSED}


def initiate_boost(user, item: Item, package: str) -> BoostPayment:
    pkg = BOOST_PACKAGES[package]
    if not settings.PESAPAL_IPN_ID:
        raise pesapal.PesapalError("PESAPAL_IPN_ID is not configured. Run `manage.py pesapal register-ipn`.")

    payment = BoostPayment.objects.create(
        user=user,
        item=item,
        package=package,
        amount=pkg["amount"],
        currency=CURRENCY,
        merchant_reference=f"DAWA-{uuid.uuid4().hex[:20].upper()}",
    )
    profile = getattr(user, "userprofile", None)
    payload = {
        "id": payment.merchant_reference,
        "currency": CURRENCY,
        "amount": float(pkg["amount"]),
        "description": f"{package} for {item.item_name}"[:100],
        "callback_url": settings.PESAPAL_CALLBACK_URL,
        "notification_id": settings.PESAPAL_IPN_ID,
        "billing_address": {
            "email_address": user.email or "",
            "phone_number": (profile.contact if profile and profile.contact else ""),
            "country_code": "UG",
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
        },
    }
    try:
        data = pesapal.submit_order(payload)
    except Exception:
        payment.status = BoostPayment.FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise

    payment.order_tracking_id = data.get("order_tracking_id")
    payment.redirect_url = data.get("redirect_url", "")
    payment.save(update_fields=["order_tracking_id", "redirect_url", "updated_at"])
    return payment


def sync_payment(order_tracking_id: str) -> BoostPayment:
    """Fetch the authoritative status from Pesapal and apply the boost once on success."""
    data = pesapal.get_transaction_status(order_tracking_id)

    with transaction.atomic():
        payment = BoostPayment.objects.select_for_update().get(order_tracking_id=order_tracking_id)
        if data.get("merchant_reference") and data["merchant_reference"] != payment.merchant_reference:
            raise pesapal.PesapalError("Merchant reference mismatch.")

        new_status = STATUS_CODES.get(data.get("status_code"), payment.status)
        paid = Decimal(str(data.get("amount") or 0))
        if new_status == BoostPayment.COMPLETED and (
            paid < payment.amount or (data.get("currency") or "").upper() != payment.currency
        ):
            new_status = BoostPayment.INVALID

        payment.status = new_status
        payment.payment_method = data.get("payment_method") or ""
        payment.confirmation_code = data.get("confirmation_code") or ""
        payment.raw_status = data

        if payment.status == BoostPayment.COMPLETED and payment.boost_applied_at is None:
            _apply_boost(payment)

        payment.save()
    return payment


def _apply_boost(payment: BoostPayment) -> None:
    now = timezone.now()
    latest = (
        BoostPayment.objects.filter(item=payment.item, boost_expires_at__gt=now)
        .exclude(pk=payment.pk)
        .order_by("-boost_expires_at")
        .values_list("boost_expires_at", flat=True)
        .first()
    )
    start = latest or now
    payment.boost_applied_at = now
    payment.boost_expires_at = start + timedelta(days=BOOST_PACKAGES[payment.package]["days"])
    Item.objects.filter(pk=payment.item_id).update(subscription_package=payment.package)


def expire_boosts() -> int:
    now = timezone.now()
    active_items = BoostPayment.objects.filter(boost_expires_at__gt=now).values("item_id")
    expired_items = (
        BoostPayment.objects.filter(boost_expires_at__lte=now).exclude(item_id__in=active_items).values("item_id")
    )
    return Item.objects.filter(pk__in=expired_items, subscription_package__in=BOOST_PACKAGES.keys()).update(
        subscription_package=None
    )
