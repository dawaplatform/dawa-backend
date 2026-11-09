from django.contrib.auth.models import User
from django.db import models

from DawaApp.models import Item


class BoostPayment(models.Model):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INVALID = "INVALID"
    REVERSED = "REVERSED"
    STATUS_CHOICES = [(s, s) for s in (PENDING, COMPLETED, FAILED, INVALID, REVERSED)]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="boost_payments")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="boost_payments")
    package = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="UGX")
    merchant_reference = models.CharField(max_length=50, unique=True)
    order_tracking_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    redirect_url = models.URLField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    payment_method = models.CharField(max_length=50, blank=True)
    confirmation_code = models.CharField(max_length=100, blank=True)
    raw_status = models.JSONField(null=True, blank=True)
    boost_applied_at = models.DateTimeField(null=True, blank=True)
    boost_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.merchant_reference} {self.package} {self.status}"
