from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from artwork.models import Artwork
from orders.cancellation import can_buyer_cancel
from orders.models import Order, OrderItem


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ArtistFulfillmentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.buyer = User.objects.create_user('shipping-buyer')
        self.a = User.objects.create_user('artist-a')
        self.b = User.objects.create_user('artist-b')
        self.other = User.objects.create_user('unrelated-artist')
        self.staff = User.objects.create_user('ordinary-staff', is_staff=True)
        group = Group.objects.get_or_create(name='Artists')[0]
        for artist in (self.a, self.b, self.other):
            artist.groups.add(group)
        self.order = Order.objects.create(
            user=self.buyer, first_name='Buyer', last_name='Test', email='buyer@example.com',
            address='Private buyer address', city='Jeddah', postal_code='12345', country='SA',
            paid=True, status='processing',
        )
        self.art_a = Artwork.objects.create(artist=self.a, title='Art A', price='20', stock=3, image='a.jpg')
        self.art_a2 = Artwork.objects.create(artist=self.a, title='Art A second', price='30', stock=3, image='a2.jpg')
        self.art_b = Artwork.objects.create(artist=self.b, title='Private Art B', price='70', stock=3, image='b.jpg')
        self.item_a = OrderItem.objects.create(order=self.order, artwork=self.art_a, price='20')
        self.item_a2 = OrderItem.objects.create(order=self.order, artwork=self.art_a2, price='30')
        self.item_b = OrderItem.objects.create(order=self.order, artwork=self.art_b, price='70')
        self.detail_url = reverse('artist_order_detail', args=[self.order.order_number])
        self.ship_url = reverse('mark_order_shipped', args=[self.order.order_number])
        self.client.force_login(self.a)

    def update(self, artist, status, **details):
        self.client.force_login(artist)
        return self.client.post(self.detail_url, dict(status=status, **details))

    def ship(self, artist, number, carrier='dhl'):
        self.client.force_login(artist)
        return self.client.post(self.ship_url, {'tracking_number': number, 'shipping_carrier': carrier})

    def refresh(self):
        for record in (self.order, self.item_a, self.item_a2, self.item_b):
            record.refresh_from_db()

    def test_preparing_changes_only_current_artists_items(self):
        self.update(self.a, 'preparing')
        self.refresh()
        self.assertEqual(self.item_a.artist_fulfillment_status, 'preparing')
        self.assertEqual(self.item_a2.artist_fulfillment_status, 'preparing')
        self.assertEqual(self.item_b.artist_fulfillment_status, 'pending')
        self.assertEqual(self.order.status, 'processing')
        self.assertIsNotNone(self.order.preparation_started_at)
        self.assertFalse(can_buyer_cancel(self.order))

    def test_shipping_one_artist_keeps_other_items_unshipped(self):
        self.ship(self.a, 'TRACK-A')
        self.refresh()
        self.assertEqual(self.item_a.tracking_number, 'TRACK-A')
        self.assertEqual(self.item_a2.tracking_number, 'TRACK-A')
        self.assertEqual(self.item_a.artist_fulfillment_status, 'shipped')
        self.assertEqual(self.item_b.artist_fulfillment_status, 'pending')
        self.assertEqual(self.item_b.tracking_number, '')
        self.assertIsNone(self.item_b.shipped_at)
        self.assertEqual(self.order.status, 'processing')
        self.assertIsNone(self.order.shipped_at)
        self.assertFalse(can_buyer_cancel(self.order))

    def test_second_artist_shipping_retains_first_tracking_and_sets_overall_shipped(self):
        self.ship(self.a, 'TRACK-A')
        self.item_a.refresh_from_db()
        first_time = self.item_a.shipped_at
        self.ship(self.b, 'TRACK-B', 'fedex')
        self.refresh()
        self.assertEqual((self.item_a.tracking_number, self.item_a.shipping_carrier), ('TRACK-A', 'dhl'))
        self.assertEqual((self.item_b.tracking_number, self.item_b.shipping_carrier), ('TRACK-B', 'fedex'))
        self.assertEqual(self.item_a.shipped_at, first_time)
        self.assertEqual(self.order.status, 'shipped')
        self.assertEqual(self.order.shipped_at, self.item_b.shipped_at)

    def test_status_form_shipping_uses_same_scoped_update(self):
        self.update(self.a, 'shipped', tracking_number='FORM-A', shipping_carrier='ups')
        self.update(self.b, 'shipped', tracking_number='FORM-B', shipping_carrier='other')
        self.refresh()
        self.assertEqual(self.item_a.tracking_number, 'FORM-A')
        self.assertEqual(self.item_b.tracking_number, 'FORM-B')
        self.assertEqual(self.order.status, 'shipped')

    def test_all_items_must_be_delivered_before_overall_delivery(self):
        self.ship(self.a, 'A');self.ship(self.b, 'B')
        self.update(self.a, 'delivered', tracking_number='A', shipping_carrier='dhl')
        self.refresh()
        self.assertEqual(self.order.status, 'shipped')
        self.assertEqual(self.item_b.artist_fulfillment_status, 'shipped')
        self.assertIsNone(self.order.delivered_at)
        self.update(self.b, 'delivered', tracking_number='B', shipping_carrier='dhl')
        self.refresh()
        self.assertEqual(self.order.status, 'delivered')
        self.assertEqual(self.order.delivered_at, self.item_b.delivered_at)

    def test_repeating_shipping_keeps_first_shipped_timestamp_and_does_not_touch_stock(self):
        self.ship(self.a, 'A');self.item_a.refresh_from_db()
        first_time = self.item_a.shipped_at
        self.ship(self.a, 'A')
        self.refresh();self.art_a.refresh_from_db()
        self.assertEqual(self.item_a.shipped_at, first_time)
        self.assertEqual(self.art_a.stock, 3)

    def test_preparation_marker_survives_reverting_to_pending(self):
        self.update(self.a, 'preparing')
        self.update(self.a, 'pending')
        self.refresh()
        self.assertIsNotNone(self.order.preparation_started_at)
        self.assertFalse(can_buyer_cancel(self.order))

    def test_notes_are_private_to_the_artist_in_both_directions(self):
        self.update(self.a, 'preparing', artist_notes='ONLY-A-SECRET')
        self.update(self.b, 'preparing', artist_notes='ONLY-B-SECRET')
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'ONLY-B-SECRET')
        self.assertNotContains(response, 'ONLY-A-SECRET')
        self.client.force_login(self.a)
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'ONLY-A-SECRET')
        self.assertNotContains(response, 'ONLY-B-SECRET')
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('order_detail', args=[self.order.order_number]))
        self.assertNotContains(response, 'ONLY-A-SECRET')
        self.assertNotContains(response, 'ONLY-B-SECRET')

    def test_shipping_form_keeps_existing_private_notes(self):
        self.update(self.a, 'preparing', artist_notes='Private packing note')
        self.ship(self.a, 'A');self.refresh()
        self.assertEqual(self.item_a.artist_notes, 'Private packing note')

    def test_artist_form_does_not_show_other_tracking_or_artwork(self):
        self.ship(self.b, 'B-PRIVATE-TRACK')
        self.client.force_login(self.a)
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'Art A')
        self.assertNotContains(response, 'Private Art B')
        self.assertNotContains(response, 'B-PRIVATE-TRACK')
        self.assertContains(response, self.ship_url)
        response = self.client.get(self.ship_url)
        self.assertNotContains(response, 'Private Art B')
        self.assertNotContains(response, 'B-PRIVATE-TRACK')

    def test_buyer_sees_each_items_tracking_and_partial_status(self):
        self.ship(self.a, 'A-TRACK')
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('order_detail', args=[self.order.order_number]))
        self.assertContains(response, 'A-TRACK')
        self.assertContains(response, 'Processing')
        self.assertContains(response, 'Pending')
        self.ship(self.b, 'B-TRACK', 'fedex')
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('order_detail', args=[self.order.order_number]))
        self.assertContains(response, 'A-TRACK')
        self.assertContains(response, 'B-TRACK')
        self.assertContains(response, 'FEDEX')

    def test_dashboard_lists_only_own_items_and_own_subtotal(self):
        response = self.client.get(reverse('artist_orders_dashboard'))
        self.assertContains(response, 'Art A')
        self.assertNotContains(response, 'Private Art B')
        self.assertContains(response, '$50.00')
        self.assertNotContains(response, '$120.00')
        self.assertEqual(response.context['total_orders'], 1)
        self.assertEqual(list(response.context['status_counts'])[0]['count'], 1)

    def test_buyer_and_nonartist_staff_cannot_access_any_artist_order_endpoint(self):
        for user in (self.buyer, self.staff):
            self.client.force_login(user)
            for url in (reverse('artist_orders_dashboard'), reverse('artist_sales_analytics'), self.detail_url, self.ship_url):
                for method in ('get', 'post'):
                    with self.subTest(user=user.username, url=url, method=method):
                        response = getattr(self.client, method)(url, {'status': 'shipped', 'tracking_number': 'FORGED'})
                        self.assertEqual(response.status_code, 302)
                        self.assertEqual(response.url, reverse('order_list'))
                        self.assertNotIn(b'Private buyer address', response.content)
        self.refresh()
        self.assertEqual(self.item_a.artist_fulfillment_status, 'pending')
        self.assertEqual(self.item_b.tracking_number, '')

    def test_logged_out_requests_require_login(self):
        self.client.logout()
        for url in (reverse('artist_orders_dashboard'), reverse('artist_sales_analytics'), self.detail_url, self.ship_url):
            for method in ('get', 'post'):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn('next=', response.url)

    def test_unrelated_artist_keeps_existing_permission_banner(self):
        self.client.force_login(self.other)
        for url in (self.detail_url, self.ship_url):
            response = self.client.post(url, {'status': 'shipped', 'tracking_number': 'FORGED'})
            self.assertRedirects(response, reverse('artist_orders_dashboard'))
            self.assertIn("You don't have permission", str(list(response.wsgi_request._messages)))
        self.refresh();self.assertEqual(self.item_a.tracking_number, '')

    def test_forged_artist_and_item_ids_are_ignored(self):
        self.update(self.a, 'shipped', tracking_number='A', shipping_carrier='dhl',
                    artist_id=self.b.pk, item_id=self.item_b.pk, order_status='delivered')
        self.refresh()
        self.assertEqual(self.item_b.artist_fulfillment_status, 'pending')
        self.assertEqual(self.order.status, 'processing')

    def test_unpaid_cancelled_and_cancellation_in_progress_orders_cannot_be_updated(self):
        for state in ('unpaid', 'cancelled', 'cancelling'):
            self.order.paid = state != 'unpaid'
            self.order.status = 'cancelled' if state == 'cancelled' else 'processing'
            self.order.cancellation_requested_at = timezone.now() if state == 'cancelling' else None
            self.order.save()
            for url in (self.detail_url, self.ship_url):
                response = self.client.post(url, {'status': 'shipped', 'tracking_number': 'BAD'})
                self.assertEqual(response.status_code, 302)
            self.refresh()
            self.assertEqual(self.item_a.artist_fulfillment_status, 'pending')
            self.assertEqual(self.item_a.tracking_number, '')
            self.assertIsNone(self.order.preparation_started_at)

    def test_get_requests_do_not_change_order_or_item_state(self):
        self.client.get(self.detail_url);self.client.get(self.ship_url)
        self.refresh()
        self.assertEqual(self.order.status, 'processing')
        self.assertEqual(self.item_a.artist_fulfillment_status, 'pending')
        self.assertIsNone(self.order.preparation_started_at)

    def test_invalid_carrier_or_oversized_tracking_is_rejected_atomically(self):
        for url in (self.detail_url, self.ship_url):
            for data in ({'shipping_carrier': 'forged', 'tracking_number': 'A'}, {'tracking_number': 'x' * 101}):
                response = self.client.post(url, dict(data, status='shipped'))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['status_form' if url == self.detail_url else 'form'].errors)
        self.refresh()
        self.assertEqual(self.item_a.tracking_number, '')
        self.assertIsNone(self.order.preparation_started_at)

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True);client.force_login(self.a)
        for url in (self.detail_url, self.ship_url):
            self.assertEqual(client.post(url, {'status': 'shipped'}).status_code, 403)

    def test_manage_orders_navigation_is_visible_to_artists_only(self):
        response = self.client.get(reverse('artist_dashboard'))
        self.assertContains(response, reverse('artist_orders_dashboard'))
        self.client.force_login(self.buyer)
        response = self.client.get(reverse('order_list'))
        self.assertNotContains(response, reverse('artist_orders_dashboard'))

    def test_single_artist_orders_still_ship_and_deliver_normally(self):
        self.item_b.delete()
        self.ship(self.a, 'SINGLE');self.refresh_without_b()
        self.assertEqual(self.order.status, 'shipped')
        self.assertIsNotNone(self.order.shipped_at)
        self.update(self.a, 'delivered', tracking_number='SINGLE', shipping_carrier='dhl')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'delivered')

    def refresh_without_b(self):
        self.order.refresh_from_db();self.item_a.refresh_from_db()

    def migrate_legacy_data(self):
        migration = import_module('orders.migrations.0004_artist_item_shipping')
        migration.migrate_shipping(apps, SimpleNamespace(connection=connection))

    def test_migration_copies_unambiguous_single_artist_tracking_and_notes(self):
        self.item_b.delete()
        now = timezone.now()
        self.order.status = 'shipped';self.order.tracking_number = 'LEGACY-A'
        self.order.shipping_carrier = 'ups';self.order.artist_notes = 'Legacy private note'
        self.order.shipped_at = now;self.order.save()
        self.migrate_legacy_data();self.refresh_without_b()
        self.assertEqual(self.item_a.tracking_number, 'LEGACY-A')
        self.assertEqual(self.item_a.artist_notes, 'Legacy private note')
        self.assertEqual(self.item_a.artist_fulfillment_status, 'shipped')
        self.assertEqual(self.order.shipped_at, now)

    def test_migration_does_not_guess_mixed_order_tracking_owner_and_repairs_partial_status(self):
        self.order.status = 'shipped';self.order.shipped_at = timezone.now()
        self.order.tracking_number = 'AMBIGUOUS';self.order.artist_notes = 'UNKNOWN-ARTIST-SECRET'
        self.order.save()
        self.item_a.artist_fulfillment_status = 'shipped';self.item_a.save()
        self.migrate_legacy_data();self.refresh()
        self.assertEqual(self.order.status, 'processing')
        self.assertIsNone(self.order.shipped_at)
        self.assertEqual(self.order.tracking_number, 'AMBIGUOUS')
        self.assertEqual(self.item_a.tracking_number, '')
        self.assertEqual(self.item_b.artist_notes, '')
        self.assertFalse(can_buyer_cancel(self.order))
        response = self.client.get(self.detail_url)
        self.assertNotContains(response, 'AMBIGUOUS')
        self.assertNotContains(response, 'UNKNOWN-ARTIST-SECRET')

    def test_migration_retains_cancellation_block_after_legacy_status_was_reverted(self):
        self.order.shipped_at = timezone.now()
        self.order.save()
        self.migrate_legacy_data();self.refresh()
        self.assertIsNotNone(self.order.preparation_started_at)
        self.assertFalse(can_buyer_cancel(self.order))

    def test_shipping_write_is_atomic_if_aggregate_status_update_fails(self):
        with patch('orders.fulfillment.synchronize_order_fulfillment', side_effect=RuntimeError('test rollback')):
            with self.assertRaises(RuntimeError):
                self.ship(self.a, 'MUST-ROLL-BACK')
        self.refresh()
        self.assertEqual(self.item_a.artist_fulfillment_status, 'pending')
        self.assertEqual(self.item_a.tracking_number, '')
        self.assertIsNone(self.order.preparation_started_at)
