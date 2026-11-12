"""Consume only the cart rows captured by a newly paid order."""
from django.db.models import F

from cart.models import Cart, CartItem


def consume_purchased_cart_items(order):
    # The caller holds the order lock inside the payment transaction. Old orders
    # have no snapshot: leave their carts alone rather than guessing what to erase.
    if not order.user_id:
        return
    carts = list(Cart.objects.select_for_update().filter(user_id=order.user_id).order_by('pk'))
    cart_ids = [cart.pk for cart in carts]
    for item in order.items.order_by('pk'):
        if not item.cart_item_id_at_checkout:
            continue
        row = CartItem.objects.select_for_update().filter(
            pk=item.cart_item_id_at_checkout,
            cart_id__in=cart_ids,
            artwork_id=item.artwork_id,
        ).first()
        if row is None or row.quantity < item.quantity:
            # A removed/re-added row or reduced quantity is a later buyer edit.
            continue
        if row.quantity == item.quantity:
            row.delete()
        else:
            CartItem.objects.filter(pk=row.pk).update(quantity=F('quantity') - item.quantity)
