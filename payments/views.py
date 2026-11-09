import logging
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from DawaApp.models import Item

from . import service
from .config import BOOST_PACKAGES, CURRENCY
from .models import BoostPayment

logger = logging.getLogger(__name__)


def _serialize(p: BoostPayment) -> dict:
    return {
        "merchant_reference": p.merchant_reference,
        "order_tracking_id": p.order_tracking_id,
        "item_id": p.item_id,
        "package": p.package,
        "amount": str(p.amount),
        "currency": p.currency,
        "status": p.status,
        "payment_method": p.payment_method,
        "redirect_url": p.redirect_url,
        "boost_expires_at": p.boost_expires_at,
        "created_at": p.created_at,
    }


@api_view(["GET"])
@permission_classes([AllowAny])
def boost_packages(request):
    return Response(
        [{"package": k, "amount": str(v["amount"]), "currency": CURRENCY, "days": v["days"]} for k, v in BOOST_PACKAGES.items()]
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_boost_payment(request):
    package = request.data.get("package")
    item_id = request.data.get("item_id")
    if package not in BOOST_PACKAGES:
        return Response({"message": f"package must be one of: {', '.join(BOOST_PACKAGES)}"}, status=status.HTTP_400_BAD_REQUEST)
    items = Item.objects.filter(pk=item_id)
    profile = getattr(request.user, "userprofile", None)
    if not (profile and profile.role == "Admin"):
        items = items.filter(seller=request.user)
    item = items.first()
    if not item:
        return Response({"message": "Item not found."}, status=status.HTTP_404_NOT_FOUND)

    try:
        payment = service.initiate_boost(request.user, item, package)
    except Exception:
        logger.exception("Pesapal order submission failed")
        return Response({"message": "Could not start payment. Please try again."}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(_serialize(payment), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def boost_payment_detail(request, merchant_reference):
    payment = get_object_or_404(BoostPayment, merchant_reference=merchant_reference, user=request.user)
    if payment.status == BoostPayment.PENDING and payment.order_tracking_id:
        try:
            payment = service.sync_payment(payment.order_tracking_id)
        except Exception:
            logger.exception("Pesapal status sync failed for %s", merchant_reference)
    return Response(_serialize(payment))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_boost_payments(request):
    return Response([_serialize(p) for p in BoostPayment.objects.filter(user=request.user)[:50]])


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def pesapal_ipn(request):
    params = request.query_params if request.method == "GET" else request.data
    tracking_id = params.get("OrderTrackingId")
    merchant_ref = params.get("OrderMerchantReference")
    notification_type = params.get("OrderNotificationType", "IPNCHANGE")
    ack = {"orderNotificationType": notification_type, "orderTrackingId": tracking_id, "orderMerchantReference": merchant_ref}

    if not tracking_id:
        return Response({**ack, "status": 500}, status=status.HTTP_400_BAD_REQUEST)
    try:
        service.sync_payment(tracking_id)
        ack["status"] = 200
    except Exception:
        logger.exception("Pesapal IPN processing failed for %s", tracking_id)
        ack["status"] = 500
    return Response(ack)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def pesapal_callback(request):
    tracking_id = request.query_params.get("OrderTrackingId")
    payment_status = "PENDING"
    reference = request.query_params.get("OrderMerchantReference", "")
    try:
        if tracking_id:
            payment_status = service.sync_payment(tracking_id).status
    except Exception:
        logger.exception("Pesapal callback sync failed for %s", tracking_id)
    return redirect(f"{settings.PESAPAL_RESULT_URL}?{urlencode({'reference': reference, 'status': payment_status})}")
