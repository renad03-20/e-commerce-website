"""Artist-scoped shipping updates. Callers lock the parent order in a transaction."""
from django.utils import timezone

from artwork.permissions import is_artist_account
from .cancellation import PurchaseError, require_fulfillable


def synchronize_order_fulfillment(order):
    """The overall status describes all items, including the other artists' items."""
    if not order.paid or order.status == 'cancelled' or order.cancellation_requested_at:
        return
    items = list(order.items.all())
    all_shipped = bool(items) and all(
        item.artist_fulfillment_status in ('shipped', 'delivered') for item in items
    )
    all_delivered = bool(items) and all(
        item.artist_fulfillment_status == 'delivered' for item in items
    )
    order.status = 'delivered' if all_delivered else 'shipped' if all_shipped else 'processing'
    # An aggregate timestamp is reliable only when every item has a timestamp.
    order.shipped_at = max(item.shipped_at for item in items) if all_shipped and all(item.shipped_at for item in items) else None
    order.delivered_at = max(item.delivered_at for item in items) if all_delivered and all(item.delivered_at for item in items) else None
    order.save(update_fields=['status', 'shipped_at', 'delivered_at', 'updated'])


def update_artist_fulfillment(order, artist, data):
    require_fulfillable(order)
    items = order.items.filter(artwork__artist=artist)
    if not is_artist_account(artist) or not items.exists():
        raise PurchaseError("You don't have permission to update this order.")
    now = timezone.now()
    status = data['status']
    if status not in ('pending', 'preparing', 'shipped', 'delivered'):
        raise PurchaseError('Please choose a valid fulfillment status.')
    if not order.preparation_started_at and (
        status != 'pending' or items.exclude(artist_fulfillment_status__in=['', 'pending']).exists()
    ):
        order.preparation_started_at = now
        order.save(update_fields=['preparation_started_at', 'updated'])
    changes = {'artist_fulfillment_status': status}
    # Shipping-only forms do not submit notes; preserve those notes.
    for field in ('tracking_number', 'shipping_carrier', 'artist_notes'):
        if field in data:
            changes[field] = data[field]
    items.update(**changes)
    if status in ('shipped', 'delivered'):
        items.filter(shipped_at__isnull=True).update(shipped_at=now)
    if status == 'delivered':
        items.filter(delivered_at__isnull=True).update(delivered_at=now)
    synchronize_order_fulfillment(order)
