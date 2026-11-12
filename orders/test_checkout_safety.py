"""Regression checks for checkout races, cart edits and durable order history."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import stripe
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from artwork.forms import ArtworkForm, CommissionAcceptForm
from artwork.models import Artwork
from cart.models import Cart, CartItem
from orders.cancellation import PurchaseError, checkout, confirm_payment, _record
from orders.models import Order, OrderItem, PurchaseEmailJob
from orders import test_cancellation as fixtures


@override_settings(ROOT_URLCONF='orders.test_cancellation', TEMPLATES=fixtures.TEST_TEMPLATES,
                   STRIPE_SECRET_KEY='sk_test_mock_only',
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CheckoutSafetyTests(TestCase):
    setUp = fixtures.CancellationTests.setUp
    create_session = fixtures.CancellationTests.create_session
    create_refund = fixtures.CancellationTests.create_refund
    expire = fixtures.CancellationTests.expire
    paid_session = fixtures.CancellationTests.paid_session
    pay = fixtures.CancellationTests.pay
    cancel_url = fixtures.CancellationTests.cancel_url

    def cart_row(self, quantity=1, artwork=None):
        cart, _ = Cart.objects.get_or_create(user=self.buyer)
        return CartItem.objects.create(cart=cart, artwork=artwork or self.art, quantity=quantity)

    def snapshot(self, row):
        self.item.cart_item_id_at_checkout = row.pk
        self.item.save(update_fields=['cart_item_id_at_checkout'])

    def assert_stock(self, expected):
        self.art.refresh_from_db()
        self.assertEqual(self.art.stock, expected)

    def test_order_creation_captures_cart_row_and_price(self):
        row = self.cart_row()
        response = self.client.post(reverse('order_create'), {
            'first_name': 'Test', 'last_name': 'Buyer', 'email': 'buyer@example.com',
            'address': 'Street', 'city': 'Jeddah', 'postal_code': '12345', 'country': 'SA',
        })
        self.assertRedirects(response, reverse('payment_process'), fetch_redirect_response=False)
        order = Order.objects.get(order_number=self.client.session['order_id'])
        self.assertEqual(order.items.get().cart_item_id_at_checkout, row.pk)
        self.assertEqual(order.items.get().price, Decimal('20.00'))
        self.assertFalse(order.paid)
        self.assertTrue(CartItem.objects.filter(pk=row.pk).exists())
        self.assert_stock(4)

    def test_failed_line_creation_rolls_back_order(self):
        self.cart_row()
        count = Order.objects.count()
        with patch('orders.views.OrderItem.objects.create', side_effect=RuntimeError('test line write failure')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('order_create'), {
                    'first_name': 'Test', 'last_name': 'Buyer', 'email': 'buyer@example.com',
                    'address': 'Street', 'city': 'Jeddah', 'postal_code': '12345', 'country': 'SA',
                })
        self.assertEqual(Order.objects.count(), count)
        self.assertNotIn('order_id', self.client.session)

    def test_payment_consumes_snapshot_without_browser_return(self):
        row = self.cart_row(); self.snapshot(row)
        self.pay()
        self.assertFalse(CartItem.objects.filter(pk=row.pk).exists())
        self.assert_stock(3)
        self.assertEqual(PurchaseEmailJob.objects.count(), 2)

    def test_unrelated_artwork_added_during_checkout_is_preserved(self):
        row = self.cart_row(); self.snapshot(row)
        other_art = Artwork.objects.create(artist=self.artist, title='Later art', price=5, stock=4, image='later.jpg')
        later = self.cart_row(artwork=other_art)
        self.pay()
        later.refresh_from_db(); self.assertEqual(later.quantity, 1)
        self.assertFalse(CartItem.objects.filter(pk=row.pk).exists())

    def test_extra_copies_added_during_checkout_remain(self):
        row = self.cart_row(quantity=3); self.snapshot(row)
        self.pay()
        row.refresh_from_db(); self.assertEqual(row.quantity, 2)
        self.assert_stock(3)

    def test_reduced_quantity_is_a_later_edit_and_is_preserved(self):
        row = self.cart_row(quantity=1)
        self.item.quantity = 2; self.item.save()
        self.snapshot(row)
        self.pay()
        row.refresh_from_db(); self.assertEqual(row.quantity, 1)
        self.assert_stock(2)

    def test_removed_and_readded_artwork_is_preserved(self):
        row = self.cart_row(); self.snapshot(row); row.delete()
        replacement = self.cart_row()
        self.pay()
        self.assertTrue(CartItem.objects.filter(pk=replacement.pk).exists())

    def test_legacy_order_without_snapshot_does_not_guess_at_cart_cleanup(self):
        row = self.cart_row()
        self.pay()
        self.assertTrue(CartItem.objects.filter(pk=row.pk).exists())

    def test_snapshot_cannot_consume_a_different_buyers_cart(self):
        cart = Cart.objects.create(user=self.other)
        row = CartItem.objects.create(cart=cart, artwork=self.art)
        self.snapshot(row); self.pay()
        self.assertTrue(CartItem.objects.filter(pk=row.pk).exists())

    def test_replayed_payment_does_not_consume_new_cart_items(self):
        row = self.cart_row(quantity=3); self.snapshot(row)
        self.pay(); self.pay()
        row.refresh_from_db(); self.assertEqual(row.quantity, 2)
        self.assert_stock(3)
        self.assertEqual(PurchaseEmailJob.objects.count(), 2)

    def test_cart_and_stock_roll_back_together_if_queue_write_fails(self):
        row = self.cart_row(); self.snapshot(row)
        with patch('orders.purchase_notifications.queue_purchase_emails', side_effect=RuntimeError('test queue failure')):
            with self.assertRaises(RuntimeError): self.pay()
        self.assertTrue(CartItem.objects.filter(pk=row.pk).exists())
        self.assert_stock(4)
        self.order.refresh_from_db(); self.assertFalse(self.order.paid)

    def test_browser_return_uses_stripe_session_and_keeps_other_active_checkout(self):
        self.pay()
        self.order.stripe_checkout_session_id = 'cs_paid'; self.order.save()
        second = Order.objects.create(user=self.buyer, email='buyer@example.com')
        state = self.client.session; state['order_id'] = second.order_number; state.save()
        row = self.cart_row()
        url = reverse('payment_completed') + '?session_id=cs_paid'
        for _ in range(2):
            response = self.client.get(url)
            self.assertRedirects(response, reverse('order_created', args=[self.order.order_number]))
        self.assertEqual(self.client.session['order_id'], second.order_number)
        self.assertTrue(CartItem.objects.filter(pk=row.pk).exists())
        self.assert_stock(3)

    def test_unpaid_or_foreign_session_cannot_confirm_payment(self):
        self.order.stripe_checkout_session_id = 'cs_unpaid'; self.order.save()
        url = reverse('payment_completed') + '?session_id=cs_unpaid'
        self.assertRedirects(self.client.get(url), reverse('order_detail', args=[self.order.order_number]))
        self.client.force_login(self.other)
        self.assertRedirects(self.client.get(url), reverse('order_list'))
        self.order.refresh_from_db(); self.assertFalse(self.order.paid)
        self.assert_stock(4)

    def test_cancel_return_uses_original_order_instead_of_another_tab(self):
        second = Order.objects.create(user=self.buyer, email='buyer@example.com')
        state = self.client.session; state['order_id'] = second.order_number; state.save()
        response = self.client.get(reverse('payment_canceled') + '?order_number=' + self.order.order_number)
        self.assertEqual(response.context['order'], self.order)
        self.assertEqual(self.client.session['order_id'], second.order_number)

    def test_checkout_urls_carry_the_original_payment_reference(self):
        state = self.client.session; state['order_id'] = self.order.order_number; state.save()
        self.client.post(reverse('payment_process'))
        kwargs = self.session_create.call_args.kwargs
        self.assertIn('?session_id={CHECKOUT_SESSION_ID}', kwargs['success_url'])
        self.assertTrue(kwargs['cancel_url'].endswith('?order_number=' + self.order.order_number))

    def test_two_buyers_last_copy_refunds_loser_without_restocking(self):
        self.art.stock = 1; self.art.save()
        self.pay()
        second = Order.objects.create(user=self.other, email='other@example.com')
        OrderItem.objects.create(order=second, artwork=self.art, price=20)
        paid = self.paid_session(second, intent='pi_second')
        confirm_payment(Order, second.pk, paid)
        confirm_payment(Order, second.pk, paid)
        second.refresh_from_db()
        self.assertTrue(second.paid)
        self.assertEqual(second.status, 'cancelled')
        self.assertIsNotNone(second.inventory_unavailable_at)
        self.assertEqual(second.refund_summary, 'succeeded')
        self.assertEqual(self.refund_create.call_count, 1)
        self.assert_stock(0)
        self.assertEqual(PurchaseEmailJob.objects.count(), 2)
        self.assertEqual(self.refund_create.call_args.kwargs['payment_intent'], 'pi_second')
        self.assertNotIn('amount', self.refund_create.call_args.kwargs)  # Full payment, including tax and shipping.

    def test_mixed_order_shortage_rolls_back_all_decrements_and_keeps_cart(self):
        row = self.cart_row(); self.snapshot(row)
        unavailable = Artwork.objects.create(artist=self.artist, title='Sold out', price=5, stock=0, image='sold.jpg')
        OrderItem.objects.create(order=self.order, artwork=unavailable, price=5)
        self.pay()
        self.assert_stock(4)
        self.assertEqual(self.order.status, 'cancelled')
        self.assertTrue(CartItem.objects.filter(pk=row.pk).exists())
        self.assertFalse(PurchaseEmailJob.objects.exists())
        self.assertContains(self.client.get(reverse('order_detail', args=[self.order.order_number])), 'sold out before payment completed')

    def test_lost_refund_response_freezes_order_and_recovers_without_fulfillment(self):
        self.art.stock = 0; self.art.save()
        paid = self.paid_session()
        def lost_response(**kwargs):
            self.create_refund(**kwargs)
            raise stripe.APIConnectionError('Test lost response')
        self.refund_create.side_effect = lost_response
        with self.assertRaises(stripe.APIConnectionError): confirm_payment(Order, self.order.pk, paid)
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.cancellation_requested_at)
        self.assertIsNotNone(self.order.inventory_unavailable_at)
        self.assertIsNone(self.order.cancelled_at)
        self.assertTrue(self.order.paid)
        self.art.stock = 5; self.art.save()
        self.refund_create.side_effect = self.create_refund
        confirm_payment(Order, self.order.pk, paid)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'cancelled')
        self.assertEqual(self.order.refund_summary, 'succeeded')
        self.assertEqual(self.refund_create.call_count, 1)
        self.assert_stock(5)
        self.assertFalse(PurchaseEmailJob.objects.exists())

    def test_buyer_retry_after_refund_failure_does_not_inflate_stock(self):
        self.art.stock = 0; self.art.save()
        self.refund_create.side_effect = stripe.APIConnectionError('Test failure')
        with self.assertRaises(stripe.APIConnectionError): self.pay()
        self.refund_create.side_effect = self.create_refund
        self.client.post(self.cancel_url())
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'cancelled')
        self.assert_stock(0)

    def test_bad_amount_cannot_trigger_a_refund_or_stock_transition(self):
        self.art.stock = 0; self.art.save()
        paid = self.paid_session(); paid['amount_total'] += 1
        with self.assertRaises(PurchaseError): confirm_payment(Order, self.order.pk, paid)
        self.assertFalse(self.refund_create.called)
        self.order.refresh_from_db(); self.assertFalse(self.order.paid)
        self.assertIsNone(self.order.cancellation_requested_at)

    def test_sdk_resources_work_for_retry_session_expiry_and_refund(self):
        session = stripe.checkout.Session.construct_from({
            'id': 'cs_sdk', 'object': 'checkout.session', 'status': 'open',
            'payment_status': 'unpaid', 'client_reference_id': self.order.order_number,
            'url': 'https://checkout.stripe.test/cs_sdk',
        }, 'sk_test_mock_only')
        self.order.stripe_checkout_session_id = session.id; self.order.save()
        self.session_retrieve.side_effect = lambda *a, **k: session
        self.assertEqual(checkout(self.order, {} ).id, 'cs_sdk')
        session.status = 'complete'; session.payment_status = 'paid'; session.payment_intent = 'pi_sdk'
        session.currency = 'usd'; session.amount_total = int(self.order.get_grand_total() * 100)
        self.session_list.side_effect = lambda **k: stripe.ListObject.construct_from({
            'object': 'list', 'data': [_record(session)], 'has_more': False,
            'url': '/v1/checkout/sessions',
        }, 'sk_test_mock_only')
        self.refund_list.side_effect = lambda **k: stripe.ListObject.construct_from({
            'object': 'list', 'data': [], 'has_more': False, 'url': '/v1/refunds',
        }, 'sk_test_mock_only')
        self.refund_create.side_effect = lambda **k: stripe.Refund.construct_from({
            'id': 're_sdk', 'object': 'refund', 'status': 'succeeded', 'payment_intent': 'pi_sdk',
            'metadata': {'cancellation_reference': self.order.order_number},
        }, 'sk_test_mock_only')
        self.client.post(self.cancel_url())
        self.order.refresh_from_db(); self.assertEqual(self.order.refund_summary, 'succeeded')
        self.assertEqual(self.order.status, 'cancelled')

    def test_ordered_artwork_is_protected_at_model_and_view(self):
        row = self.cart_row()
        with self.assertRaises(ProtectedError): self.art.delete()
        self.client.force_login(self.artist)
        response = self.client.post(reverse('artwork_delete', args=[self.art.pk]), follow=True)
        self.assertContains(response, 'linked to an order and cannot be deleted')
        self.assertTrue(Artwork.objects.filter(pk=self.art.pk).exists())
        self.assertTrue(OrderItem.objects.filter(pk=self.item.pk).exists())
        self.assertTrue(CartItem.objects.filter(pk=row.pk).exists())
        self.assertEqual(self.order.get_grand_total(), Decimal('31.60'))

    def test_never_ordered_artwork_can_still_be_deleted(self):
        art = Artwork.objects.create(artist=self.artist, title='Draft', price=20, image='draft.jpg')
        self.cart_row(artwork=art)
        self.client.force_login(self.artist)
        response = self.client.post(reverse('artwork_delete', args=[art.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Artwork.objects.filter(pk=art.pk).exists())
        self.assertFalse(CartItem.objects.filter(artwork_id=art.pk).exists())

    def test_cart_removal_requires_post_and_ownership(self):
        row = self.cart_row()
        url = reverse('cart:remove_from_cart', args=[row.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(self.other)
        self.client.post(url)
        self.assertTrue(CartItem.objects.filter(pk=row.pk).exists())
        self.client.force_login(self.buyer)
        self.client.post(url)
        self.assertFalse(CartItem.objects.filter(pk=row.pk).exists())

    def test_commission_price_and_artist_deadline_are_validated_on_server(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        for price in ('0', '-1', '0.49', '1000000'):
            form = CommissionAcceptForm({'price': price})
            self.assertFalse(form.is_valid()); self.assertIn('price', form.errors)
        form = CommissionAcceptForm({'price': '0.50', 'artist_deadline': yesterday.isoformat()})
        self.assertFalse(form.is_valid()); self.assertIn('artist_deadline', form.errors)
        self.assertTrue(CommissionAcceptForm({'price': '0.50', 'artist_deadline': timezone.localdate().isoformat()}).is_valid())
        for price in ('0', '-1'):
            form = ArtworkForm({'price': price})
            self.assertFalse(form.is_valid()); self.assertIn('price', form.errors)
