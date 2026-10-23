import unittest
from decimal import Decimal

from shopkit.cart import Cart


class CartTest(unittest.TestCase):
    def test_add_and_total(self):
        cart = Cart()
        cart.add("beans-1kg", "18.50", 2)
        cart.add("mug", "9.00")
        self.assertEqual(cart.count(), 3)
        self.assertEqual(cart.total(), Decimal("46.00"))

    def test_remove(self):
        cart = Cart()
        cart.add("mug", "9.00", 2)
        cart.remove("mug")
        self.assertEqual(cart.count(), 1)
        cart.remove("mug")
        self.assertEqual(cart.count(), 0)


if __name__ == "__main__":
    unittest.main()
