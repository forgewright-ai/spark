"""A shopping cart: lines of a product, a unit price and a qty."""

from decimal import Decimal


class Line:
    def __init__(self, sku, price, qty=1):
        if qty < 1:
            raise ValueError("qty must be 1 or more")
        self.sku = sku
        self.price = Decimal(price)
        self.qty = qty

    def subtotal(self):
        return self.price * self.qty


class Cart:
    def __init__(self):
        self.lines = {}

    def add(self, sku, price, qty=1):
        line = self.lines.get(sku)
        if line:
            line.qty += qty
        else:
            self.lines[sku] = Line(sku, price, qty)

    def remove(self, sku, qty=1):
        line = self.lines[sku]
        line.qty -= qty
        if line.qty <= 0:
            del self.lines[sku]

    def count(self):
        return sum(line.qty for line in self.lines.values())

    def total(self):
        return sum((line.subtotal() for line in self.lines.values()), Decimal("0"))
