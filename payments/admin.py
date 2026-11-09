from django.contrib import admin

from .models import BoostPayment


@admin.register(BoostPayment)
class BoostPaymentAdmin(admin.ModelAdmin):
    list_display = ("merchant_reference", "user", "item", "package", "amount", "status", "boost_expires_at", "created_at")
    list_filter = ("status", "package")
    search_fields = ("merchant_reference", "order_tracking_id", "user__email", "item__item_name")
    readonly_fields = [f.name for f in BoostPayment._meta.fields]
