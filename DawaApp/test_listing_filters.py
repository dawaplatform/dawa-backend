from unittest.mock import MagicMock

from django.test import SimpleTestCase

from DawaApp.listing_filters import SORTS, InvalidFilter, apply_listing_filters


def _items():
    items = MagicMock()
    items.filter.return_value = items
    items.order_by.return_value = items
    return items


class ListingFilterTests(SimpleTestCase):
    def test_no_filters_defaults_to_newest_first(self):
        items = _items()
        apply_listing_filters(items, {})
        items.filter.assert_not_called()
        items.order_by.assert_called_once_with(*SORTS["newest"])

    def test_price_range_location_and_negotiable(self):
        items = _items()
        apply_listing_filters(
            items, {"min_price": "1000", "max_price": 5000, "location": " Kampala ", "negotiable": True}
        )
        kwargs = [call.kwargs for call in items.filter.call_args_list]
        self.assertIn({"item_location__icontains": "Kampala"}, kwargs)
        self.assertIn({"item_negotiable": True}, kwargs)
        self.assertEqual(sum("item_price__gte" in k or "item_price__lte" in k for k in kwargs), 2)

    def test_negotiable_false_is_not_a_filter(self):
        items = _items()
        apply_listing_filters(items, {"negotiable": False})
        items.filter.assert_not_called()

    def test_invalid_values_are_rejected(self):
        for params in (
            {"min_price": "abc"},
            {"max_price": "-5"},
            {"min_price": "10", "max_price": "5"},
            {"sort": "random"},
        ):
            with self.subTest(params=params), self.assertRaises(InvalidFilter):
                apply_listing_filters(_items(), params)
