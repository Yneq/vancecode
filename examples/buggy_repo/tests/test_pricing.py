import unittest
from pricing import total_cents


class PricingTests(unittest.TestCase):
    def test_no_discount(self):
        self.assertEqual(total_cents([(1000, 2)], shipping_cents=100), 2100)

    def test_shipping_is_not_discounted(self):
        self.assertEqual(total_cents([(1000, 2)], 10, 100), 1900)

    def test_round_down_merchandise_before_shipping(self):
        self.assertEqual(total_cents([(999, 1)], 15, 125), 974)

    def test_full_discount_preserves_shipping(self):
        self.assertEqual(total_cents([(999, 1)], 100, 125), 125)
