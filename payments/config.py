import os
from decimal import Decimal

CURRENCY = "UGX"

# Prices (UGX) come from .env; Pesapal charges whatever amount we send per order.
BOOST_PACKAGES = {
    "Boost 7": {"amount": Decimal(os.getenv("BOOST_7_PRICE", "10000")), "days": 7},
    "Boost 30": {"amount": Decimal(os.getenv("BOOST_30_PRICE", "30000")), "days": 30},
}
