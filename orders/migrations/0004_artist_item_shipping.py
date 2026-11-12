from django.db import migrations, models


def migrate_shipping(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    Item = apps.get_model('orders', 'OrderItem')
    database = schema_editor.connection.alias
    for order in Order.objects.using(database).all().iterator():
        items = list(Item.objects.using(database).filter(order_id=order.pk).select_related('artwork'))
        if not items:
            continue
        artist_ids = {item.artwork.artist_id for item in items}
        if len(artist_ids) == 1:
            # Shared legacy tracking has an unambiguous owner only in this case.
            changes = {
                'tracking_number': order.tracking_number,
                'shipping_carrier': order.shipping_carrier,
                'shipped_at': order.shipped_at,
                'delivered_at': order.delivered_at,
                'artist_notes': order.artist_notes,
            }
            if order.status in ('shipped', 'delivered') and all(item.artist_fulfillment_status in ('', 'pending') for item in items):
                changes['artist_fulfillment_status'] = order.status
            Item.objects.using(database).filter(order_id=order.pk).update(**changes)
            for item in items:
                for field, value in changes.items():
                    setattr(item, field, value)
        # For mixed orders preserve the old shared fields as historical data,
        # without guessing which artist supplied them or exposing private notes.
        changes = {}
        if not order.preparation_started_at and (
            order.shipped_at or order.delivered_at
            or any(item.artist_fulfillment_status not in ('', 'pending') for item in items)
        ):
            changes['preparation_started_at'] = order.shipped_at or order.updated
        if order.paid and order.status != 'cancelled' and not order.cancellation_requested_at:
            all_shipped = all(item.artist_fulfillment_status in ('shipped', 'delivered') for item in items)
            all_delivered = all(item.artist_fulfillment_status == 'delivered' for item in items)
            changes['status'] = 'delivered' if all_delivered else 'shipped' if all_shipped else 'processing'
            changes['shipped_at'] = max(item.shipped_at for item in items) if all_shipped and all(item.shipped_at for item in items) else None
            changes['delivered_at'] = max(item.delivered_at for item in items) if all_delivered and all(item.delivered_at for item in items) else None
        if changes:
            Order.objects.using(database).filter(pk=order.pk).update(**changes)


class Migration(migrations.Migration):
    dependencies = [('orders', '0003_order_cancellation_refunds_and_more')]

    operations = [
        migrations.AddField(model_name='orderitem', name='tracking_number', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='orderitem', name='shipping_carrier', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='orderitem', name='shipped_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='orderitem', name='delivered_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='orderitem', name='artist_notes', field=models.TextField(blank=True)),
        migrations.RunPython(migrate_shipping, migrations.RunPython.noop),
    ]
