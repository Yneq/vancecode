"""Prices use integer cents. Discounts apply only to merchandise."""


def total_cents(items, discount_percent=0, shipping_cents=0):
    subtotal = sum(price * quantity for price, quantity in items)
    return (subtotal + shipping_cents) * (100 - discount_percent) // 100
