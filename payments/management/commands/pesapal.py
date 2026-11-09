import json

from django.conf import settings
from django.core.management.base import BaseCommand

from payments import pesapal, service


class Command(BaseCommand):
    help = "Pesapal helpers: token | register-ipn <url> | list-ipns | status <order_tracking_id> | sync <order_tracking_id> | expire-boosts"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["token", "register-ipn", "list-ipns", "status", "sync", "expire-boosts"])
        parser.add_argument("value", nargs="?")
        parser.add_argument("--method", default="GET", choices=["GET", "POST"])

    def handle(self, action, value=None, method="GET", **opts):
        self.stdout.write(f"Pesapal API: {settings.PESAPAL_API_URL}")
        if action == "token":
            token = pesapal.get_token(force_refresh=True)
            self.stdout.write(self.style.SUCCESS(f"Token OK ({token[:16]}...)"))
        elif action == "register-ipn":
            url = value or settings.PESAPAL_IPN_URL
            data = pesapal.register_ipn(url, method)
            self._dump(data)
            self.stdout.write(self.style.SUCCESS(f"Set PESAPAL_IPN_ID={data.get('ipn_id')} in .env"))
        elif action == "list-ipns":
            self._dump(pesapal.get_ipn_list())
        elif action == "status":
            self._dump(pesapal.get_transaction_status(value))
        elif action == "sync":
            p = service.sync_payment(value)
            self.stdout.write(f"{p.merchant_reference}: {p.status} (expires {p.boost_expires_at})")
        elif action == "expire-boosts":
            self.stdout.write(f"Expired boosts on {service.expire_boosts()} item(s)")

    def _dump(self, data):
        self.stdout.write(json.dumps(data, indent=2, default=str))
