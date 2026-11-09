from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from DawaApp.models import Category, Item, SubCategory
from payments import service
from payments.models import BoostPayment


@override_settings(PESAPAL_IPN_ID="ipn-123", PESAPAL_CALLBACK_URL="https://example.com/cb")
class BoostPaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("seller", "s@example.com", "pw")
        cat = Category.objects.create(category_name="Cat")
        sub = SubCategory.objects.create(subcategory_name="Sub", subcategory_category=cat)
        self.item = Item.objects.create(
            seller=self.user, item_name="Phone", item_price=100, item_location="Kampala",
            item_subcategory=sub, item_description="d",
        )

    def _start(self):
        with patch("payments.pesapal.submit_order", return_value={"order_tracking_id": "trk-1", "redirect_url": "https://pay/x"}):
            return service.initiate_boost(self.user, self.item, "Boost 7")

    def _status(self, payment, **overrides):
        data = {"status_code": 1, "amount": float(payment.amount), "currency": "UGX",
                "merchant_reference": payment.merchant_reference, "payment_method": "MTN"}
        data.update(overrides)
        return patch("payments.pesapal.get_transaction_status", return_value=data)

    def test_completed_payment_applies_boost_once(self):
        payment = self._start()
        with self._status(payment):
            service.sync_payment("trk-1")
            first_expiry = BoostPayment.objects.get(pk=payment.pk).boost_expires_at
            service.sync_payment("trk-1")
        payment.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.status, BoostPayment.COMPLETED)
        self.assertEqual(payment.boost_expires_at, first_expiry)
        self.assertEqual(self.item.subscription_package, "Boost 7")

    def test_underpayment_is_not_applied(self):
        payment = self._start()
        with self._status(payment, amount=float(payment.amount - Decimal("1"))):
            service.sync_payment("trk-1")
        payment.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(payment.status, BoostPayment.INVALID)
        self.assertIsNone(self.item.subscription_package)

    def test_unpaid_order_stays_pending(self):
        payment = self._start()
        with self._status(payment, status_code=0):
            service.sync_payment("trk-1")
        payment.refresh_from_db()
        self.assertEqual(payment.status, BoostPayment.PENDING)
