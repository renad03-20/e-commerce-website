from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import HttpResponse
from django.test import TestCase, Client, override_settings
from django.urls import include, path, reverse
from django.utils import timezone

from artwork.models import Artwork, CustomRequest
from cart.models import Cart, CartItem
from orders.models import Order, OrderItem
from orders.cancellation import (
    PurchaseError, cancel_purchase, can_buyer_cancel, checkout,
    confirm_payment, update_refund,
)

urlpatterns = [
    path('orders/', include('orders.urls')),
    path('artwork/', include('artwork.urls')),
    path('cart/', include('cart.urls')),
    path('login/', lambda r: HttpResponse('Login'), name='login'),
    path('', lambda r: HttpResponse('Home'), name='home'),
]
TEST_TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': False,
    'OPTIONS': {'loaders': [('django.template.loaders.locmem.Loader', {'base.html': '{% for message in messages %}{{ message }}{% endfor %}{% block content %}{% endblock %}'}), 'django.template.loaders.app_directories.Loader'],
    'context_processors': ['django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages']}}]

class Obj(dict):
    __getattr__ = dict.__getitem__

class Page:
    def __init__(self, values): self.values = values
    def auto_paging_iter(self): return iter(self.values)


@override_settings(ROOT_URLCONF=__name__, TEMPLATES=TEST_TEMPLATES, STRIPE_SECRET_KEY='sk_test_mock_only', PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CancellationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.buyer = User.objects.create_user('buyer', password='test-password')
        self.other = User.objects.create_user('other', password='test-password')
        self.artist = User.objects.create_user('artist', password='test-password')
        self.artist.groups.add(Group.objects.get_or_create(name='Artists')[0])
        self.art = Artwork.objects.create(artist=self.artist, title='Test art', price='20.00', stock=4, image='test.jpg')
        self.order = Order.objects.create(user=self.buyer, first_name='Test', last_name='Buyer', email='test@example.com', address='Test', city='Test', postal_code='12345', country='SA')
        self.item = OrderItem.objects.create(order=self.order, artwork=self.art, price='20.00', quantity=1)
        self.commission = CustomRequest.objects.create(sender=self.buyer, receiver=self.artist, title='Commission', requirements='A painting', price='20.00')
        self.sessions = {}
        self.refunds = {}
        self.refund_number = 0
        patches = {
            'stripe.checkout.Session.list': lambda **kwargs: Page(list(self.sessions.values())),
            'stripe.checkout.Session.retrieve': lambda sid, **kwargs: self.sessions[sid],
            'stripe.checkout.Session.expire': self.expire,
            'stripe.checkout.Session.create': self.create_session,
            'stripe.Refund.list': lambda payment_intent, **kwargs: Page([r for r in self.refunds.values() if r.payment_intent == payment_intent]),
            'stripe.Refund.retrieve': lambda rid, **kwargs: self.refunds[rid],
            'stripe.Refund.create': self.create_refund,
        }
        for target, effect in patches.items():
            p = patch(target, side_effect=effect)
            mock = p.start(); self.addCleanup(p.stop)
            setattr(self, target.split('.')[-2].lower()+'_'+target.split('.')[-1], mock)
        self.client.force_login(self.buyer)

    def create_session(self, **kwargs):
        sid = f'cs_{len(self.sessions)+1}'
        s = Obj(id=sid, status='open', payment_status='unpaid', payment_intent=None, client_reference_id=kwargs['client_reference_id'], url=f'https://checkout.stripe.test/{sid}')
        self.sessions[sid] = s
        return s

    def expire(self, sid, **kwargs):
        self.sessions[sid]['status'] = 'expired'
        return self.sessions[sid]

    def create_refund(self, payment_intent, **kwargs):
        self.refund_number += 1
        r = Obj(id=f're_{self.refund_number}', payment_intent=payment_intent, status='succeeded', metadata=kwargs['metadata'])
        self.refunds[r.id] = r
        return r

    def paid_session(self, purchase=None, intent='pi_paid'):
        purchase = purchase or self.order
        ref = f'commission:{purchase.pk}' if isinstance(purchase, CustomRequest) else purchase.order_number
        amount = purchase.price if isinstance(purchase, CustomRequest) else purchase.get_grand_total()
        s = Obj(id='cs_paid', status='complete', payment_status='paid', payment_intent=intent, client_reference_id=ref, currency='usd', amount_total=int(Decimal(amount)*100))
        self.sessions[s.id] = s
        return s

    def pay(self, purchase=None):
        purchase = purchase or self.order
        confirm_payment(type(purchase), purchase.pk, self.paid_session(purchase))
        purchase.refresh_from_db()
        return purchase

    def cancel_url(self): return reverse('cancel_order', args=[self.order.order_number])
    def commission_cancel_url(self): return reverse('commission_cancel', args=[self.commission.pk])

    def test_unpaid_cancellation_preserves_cart_stock_and_payment(self):
        cart = Cart.objects.create(user=self.buyer)
        CartItem.objects.create(cart=cart, artwork=self.art, quantity=1)
        s = self.create_session(client_reference_id=self.order.order_number)
        self.order.stripe_checkout_session_id=s.id; self.order.save()
        response = self.client.post(self.cancel_url())
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db(); self.art.refresh_from_db()
        self.assertEqual(self.order.status, 'cancelled')
        self.assertFalse(self.order.paid)
        self.assertEqual(self.art.stock, 4)
        self.assertEqual(cart.items.count(), 1)
        self.assertEqual(s.status, 'expired')
        self.refund_create.assert_not_called()

    def test_paid_cancel_refunds_full_payment_and_restocks_once(self):
        self.pay()
        self.client.post(self.cancel_url()); self.client.post(self.cancel_url())
        self.order.refresh_from_db(); self.art.refresh_from_db()
        self.assertTrue(self.order.paid)  # Retain the historical payment fact.
        self.assertEqual(self.order.status, 'cancelled')
        self.assertEqual(self.art.stock, 4)
        self.assertEqual(self.refund_create.call_count, 1)
        self.assertEqual(self.refund_create.call_args.kwargs['payment_intent'], 'pi_paid')
        self.assertNotIn('amount', self.refund_create.call_args.kwargs)  # Full remaining payment.

    def test_other_buyer_cannot_cancel(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.cancel_url()).status_code, 302)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.cancellation_requested_at)
        self.session_list.assert_not_called()

    def test_anonymous_requires_login_and_get_does_not_cancel(self):
        self.client.logout()
        self.assertEqual(self.client.post(self.cancel_url()).status_code, 302)
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(self.cancel_url()).status_code, 405)
        self.order.refresh_from_db(); self.assertEqual(self.order.status, 'pending')

    def test_cancellation_requires_csrf(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.buyer)
        self.assertEqual(client.post(self.cancel_url()).status_code, 403)

    def test_preparing_item_blocks_cancellation(self):
        self.item.artist_fulfillment_status='preparing'; self.item.save()
        self.client.post(self.cancel_url())
        self.order.refresh_from_db(); self.assertIsNone(self.order.cancelled_at)
        self.session_list.assert_not_called()

    def test_starting_then_reverting_to_pending_does_not_reopen_cancellation(self):
        self.pay(); self.client.force_login(self.artist)
        url=reverse('artist_order_detail', args=[self.order.order_number])
        self.client.post(url, {'status':'preparing'})
        self.client.post(url, {'status':'pending'})
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.preparation_started_at)
        self.assertFalse(can_buyer_cancel(self.order))
        self.client.force_login(self.buyer); self.client.post(self.cancel_url())
        self.order.refresh_from_db(); self.assertIsNone(self.order.cancelled_at)

    def test_one_artist_start_blocks_whole_multi_artist_order(self):
        another = Artwork.objects.create(artist=self.other, title='Other art', price='5', stock=3, image='test.jpg')
        OrderItem.objects.create(order=self.order, artwork=another, price='5', artist_fulfillment_status='preparing')
        self.assertFalse(can_buyer_cancel(self.order))

    def test_unpaid_artist_cannot_prepare_or_ship(self):
        self.client.force_login(self.artist)
        self.client.post(reverse('artist_order_detail', args=[self.order.order_number]), {'status':'preparing'})
        self.client.post(reverse('mark_order_shipped', args=[self.order.order_number]), {'tracking_number':'TEST'})
        self.order.refresh_from_db(); self.item.refresh_from_db()
        self.assertIsNone(self.order.preparation_started_at)
        self.assertEqual(self.item.artist_fulfillment_status, 'pending')

    def test_refund_failure_freezes_work_and_retry_uses_same_request(self):
        self.pay()
        self.refund_create.side_effect = stripe.APIConnectionError('Test failure')
        self.client.post(self.cancel_url())
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.cancellation_requested_at)
        self.assertIsNone(self.order.cancelled_at)
        self.client.force_login(self.artist)
        self.client.post(reverse('artist_order_detail', args=[self.order.order_number]), {'status':'preparing'})
        self.item.refresh_from_db(); self.assertEqual(self.item.artist_fulfillment_status,'pending')
        self.refund_create.side_effect = self.create_refund
        self.client.force_login(self.buyer); self.client.post(self.cancel_url())
        self.order.refresh_from_db(); self.assertEqual(self.order.status,'cancelled')
        self.assertEqual(self.refund_create.call_args_list[0].kwargs['idempotency_key'], self.refund_create.call_args_list[1].kwargs['idempotency_key'])

    def test_lost_refund_response_is_recovered_without_second_refund(self):
        self.pay()
        def lost_response(**kwargs):
            self.create_refund(**kwargs)
            raise stripe.APIConnectionError('Response lost')
        self.refund_create.side_effect = lost_response
        self.client.post(self.cancel_url())
        self.refund_create.side_effect = self.create_refund
        self.client.post(self.cancel_url())
        self.assertEqual(self.refund_create.call_count, 1)
        self.order.refresh_from_db(); self.assertEqual(self.order.status,'cancelled')

    def test_pending_refund_is_not_displayed_as_completed(self):
        self.pay()
        def pending(**kwargs):
            r=self.create_refund(**kwargs);r['status']='pending';return r
        self.refund_create.side_effect = pending
        self.client.post(self.cancel_url())
        self.order.refresh_from_db(); self.assertEqual(self.order.refund_summary,'pending')
        response = self.client.get(reverse('order_detail', args=[self.order.order_number]))
        self.assertContains(response,'Refund status: pending')
        r = next(iter(self.refunds.values()));r['status']='succeeded';update_refund(r)
        self.order.refresh_from_db();self.assertEqual(self.order.refund_summary,'succeeded')

    def test_late_paid_webhook_refunds_without_resurrecting_or_deducting_stock(self):
        self.client.post(self.cancel_url())
        s=self.paid_session();confirm_payment(Order,self.order.pk,s);confirm_payment(Order,self.order.pk,s)
        self.order.refresh_from_db();self.art.refresh_from_db()
        self.assertEqual(self.order.status,'cancelled');self.assertEqual(self.art.stock,4)
        self.assertFalse(self.order.paid);self.assertEqual(self.refund_create.call_count,1)

    def test_payment_wins_expiry_race_is_refunded(self):
        s=self.create_session(client_reference_id=self.order.order_number)
        def paid_before_expiry(sid,**kwargs):
            s.update(self.paid_session());s['id']=sid
            raise stripe.InvalidRequestError('Session completed', 'id')
        self.session_expire.side_effect=paid_before_expiry
        self.client.post(self.cancel_url())
        self.order.refresh_from_db();self.art.refresh_from_db()
        self.assertEqual(self.order.status,'cancelled');self.assertEqual(self.art.stock,4)
        self.assertEqual(self.refund_create.call_count,1)

    def test_checkout_reused_and_cancellation_prevents_new_checkout(self):
        data={'client_reference_id':self.order.order_number}
        first=checkout(self.order,data);second=checkout(self.order,data)
        self.assertEqual(first.id,second.id);self.assertEqual(self.session_create.call_count,1)
        cancel_purchase(Order,self.order.pk,self.buyer);self.order.refresh_from_db()
        with self.assertRaises(PurchaseError):checkout(self.order,data)

    def test_legacy_checkout_discovery_expires_all_matching_sessions(self):
        s1=self.create_session(client_reference_id=self.order.order_number)
        s2=self.create_session(client_reference_id=self.order.order_number)
        other=self.create_session(client_reference_id='another-order')
        self.client.post(self.cancel_url())
        self.assertEqual(s1.status,'expired');self.assertEqual(s2.status,'expired');self.assertEqual(other.status,'open')

    def test_duplicate_payment_deducts_stock_once(self):
        s=self.paid_session();confirm_payment(Order,self.order.pk,s);confirm_payment(Order,self.order.pk,s)
        self.art.refresh_from_db();self.assertEqual(self.art.stock,3)

    def test_payment_amount_currency_and_unpaid_events_are_rejected(self):
        s=self.paid_session();s['payment_status']='unpaid';confirm_payment(Order,self.order.pk,s)
        self.order.refresh_from_db();self.assertFalse(self.order.paid)
        s['payment_status']='paid';s['amount_total']=1
        with self.assertRaises(PurchaseError):confirm_payment(Order,self.order.pk,s)
        s['amount_total']=int(self.order.get_grand_total()*100);s['currency']='eur'
        with self.assertRaises(PurchaseError):confirm_payment(Order,self.order.pk,s)

    def test_commission_payment_waits_for_explicit_artist_start(self):
        self.commission.status='awaiting_payment';self.commission.save();self.pay(self.commission)
        self.assertEqual(self.commission.status,'awaiting_artist');self.assertIsNone(self.commission.work_started_at)
        self.client.force_login(self.artist)
        response=self.client.get(reverse('commission_detail',args=[self.commission.pk]));self.assertContains(response,'Start Work')
        self.client.post(reverse('commission_start_work',args=[self.commission.pk]))
        self.commission.refresh_from_db();self.assertEqual(self.commission.status,'in_progress');self.assertIsNotNone(self.commission.work_started_at)
        self.client.force_login(self.buyer);self.client.post(self.commission_cancel_url())
        self.commission.refresh_from_db();self.assertEqual(self.commission.status,'in_progress')
        self.refund_create.assert_not_called()

    def test_paid_commission_can_cancel_before_start_with_refund(self):
        self.commission.status='awaiting_payment';self.commission.save();self.pay(self.commission)
        self.client.post(self.commission_cancel_url());self.client.post(self.commission_cancel_url())
        self.commission.refresh_from_db();self.assertEqual(self.commission.status,'canceled')
        self.assertIsNotNone(self.commission.paid_at);self.assertEqual(self.refund_create.call_count,1)

    def test_unpaid_commission_can_cancel_without_stock_change_or_refund(self):
        self.client.post(self.commission_cancel_url())
        self.commission.refresh_from_db();self.art.refresh_from_db()
        self.assertEqual(self.commission.status,'canceled');self.assertEqual(self.art.stock,4)
        self.refund_create.assert_not_called()

    def test_commission_start_requires_artist_payment_and_post(self):
        url=reverse('commission_start_work',args=[self.commission.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        self.client.post(url);self.commission.refresh_from_db();self.assertIsNone(self.commission.work_started_at)
        self.client.force_login(self.artist);self.client.post(url)
        self.commission.refresh_from_db();self.assertIsNone(self.commission.work_started_at)

    def test_foreign_buyer_cannot_cancel_commission(self):
        self.client.force_login(self.other);self.client.post(self.commission_cancel_url())
        self.commission.refresh_from_db();self.assertIsNone(self.commission.cancellation_requested_at)

    def test_failed_commission_cancellation_blocks_start_and_delivery(self):
        self.commission.status='awaiting_payment';self.commission.save();self.pay(self.commission)
        self.refund_create.side_effect=stripe.APIConnectionError('Test failure')
        self.client.post(self.commission_cancel_url());self.client.force_login(self.artist)
        self.client.post(reverse('commission_start_work',args=[self.commission.pk]))
        self.client.post(reverse('commission_delivery',args=[self.commission.pk]),{'external_link':'https://example.com/art'})
        self.commission.refresh_from_db();self.assertEqual(self.commission.status,'awaiting_artist');self.assertEqual(self.commission.deliveries.count(),0)

    def test_success_return_url_cannot_mark_commission_paid(self):
        self.client.get(reverse('commission_payment_completed',args=[self.commission.pk]))
        self.commission.refresh_from_db();self.assertIsNone(self.commission.paid_at)
        self.assertEqual(self.commission.status,'requested')

    def test_old_in_progress_commission_is_not_reopened_by_new_feature(self):
        self.commission.status='in_progress';self.commission.paid_at=timezone.now();self.commission.save()
        self.client.post(self.commission_cancel_url())
        self.commission.refresh_from_db();self.assertEqual(self.commission.status,'in_progress')
        self.session_list.assert_not_called()

    def test_completed_commission_duplicate_payment_event_is_not_refunded(self):
        self.commission.status='awaiting_payment';self.commission.save();s=self.paid_session(self.commission)
        confirm_payment(CustomRequest,self.commission.pk,s)
        self.commission.refresh_from_db();self.commission.status='completed';self.commission.save()
        confirm_payment(CustomRequest,self.commission.pk,s)
        self.refund_create.assert_not_called()

    def test_cancelled_order_cannot_open_checkout_or_success_confirmation(self):
        self.pay();self.client.post(self.cancel_url())
        session=self.client.session;session['order_id']=self.order.order_number;session.save()
        for name in ('payment_process','payment_completed'):
            response=self.client.get(reverse(name));self.assertEqual(response.status_code,302)
            self.assertEqual(response.url,reverse('order_detail',args=[self.order.order_number]))
        response=self.client.get(reverse('order_created',args=[self.order.order_number]));self.assertEqual(response.status_code,302)

    def test_failed_refund_event_is_visible_without_restocking_twice(self):
        self.pay();self.client.post(self.cancel_url())
        r=next(iter(self.refunds.values()));r['status']='failed';update_refund(r)
        self.order.refresh_from_db();self.art.refresh_from_db()
        self.assertEqual(self.order.refund_summary,'failed');self.assertEqual(self.art.stock,4)

    def test_artist_can_still_cancel_their_commission_and_refund_buyer(self):
        self.commission.status='awaiting_payment';self.commission.save();self.pay(self.commission)
        self.client.force_login(self.artist)
        self.client.post(reverse('commission_start_work', args=[self.commission.pk]))
        self.client.post(self.commission_cancel_url(), {'cancel_reason':'Unable to finish'})
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.status,'canceled')
        self.assertEqual(self.commission.cancel_reason,'Unable to finish')
        self.assertEqual(self.refund_create.call_count,1)

    def test_unrelated_artist_cannot_prepare_or_ship_order(self):
        self.pay();self.client.force_login(self.other)
        for name in ('artist_order_detail','mark_order_shipped'):
            response=self.client.post(reverse(name,args=[self.order.order_number]),{'status':'preparing'})
            self.assertEqual(response.url,reverse('artist_orders_dashboard'))
        self.order.refresh_from_db();self.assertIsNone(self.order.preparation_started_at)

    def test_buyer_can_see_cancel_button_and_artist_cannot_start_after_cancel(self):
        response=self.client.get(reverse('order_detail',args=[self.order.order_number]))
        self.assertContains(response,'Cancel Order')
        self.pay();self.client.post(self.cancel_url());self.client.force_login(self.artist)
        self.client.post(reverse('artist_order_detail',args=[self.order.order_number]),{'status':'preparing'})
        self.client.post(reverse('mark_order_shipped',args=[self.order.order_number]),{'tracking_number':'TEST'})
        self.order.refresh_from_db();self.item.refresh_from_db()
        self.assertIsNone(self.order.shipped_at);self.assertEqual(self.item.artist_fulfillment_status,'pending')
        response=self.client.get(reverse('artist_order_detail',args=[self.order.order_number]))
        self.assertNotContains(response,'class="status-form"')
        self.assertNotContains(response,'Mark as Shipped')

    def test_commission_cancel_note_and_flash_message_survive(self):
        self.client.post(self.commission_cancel_url(),{'cancel_reason':'Changed my mind'})
        response=self.client.get(reverse('commission_detail',args=[self.commission.pk]))
        self.assertContains(response,'Changed my mind')
        self.assertContains(response,'Commission cancelled.')
        self.assertNotContains(response,'>Start Work<')

    def test_webhook_signature_failure_is_rejected(self):
        with patch('orders.views.stripe.Webhook.construct_event',side_effect=stripe.SignatureVerificationError('Invalid','sig')):
            response=self.client.post(reverse('stripe_webhook'),data=b'{}',content_type='application/json')
        self.assertEqual(response.status_code,400)

    def test_webhook_confirms_payment_and_handles_refund_event(self):
        event={'type':'checkout.session.completed','data':{'object':self.paid_session()}}
        with patch('orders.views.stripe.Webhook.construct_event',return_value=event):
            response=self.client.post(reverse('stripe_webhook'),data=b'{}',content_type='application/json')
        self.assertEqual(response.status_code,200);self.order.refresh_from_db();self.assertTrue(self.order.paid)
        self.client.post(self.cancel_url())
        refund=next(iter(self.refunds.values()));refund['status']='failed'
        event={'type':'refund.failed','data':{'object':refund}}
        with patch('orders.views.stripe.Webhook.construct_event',return_value=event):
            self.assertEqual(self.client.post(reverse('stripe_webhook'),data=b'{}',content_type='application/json').status_code,200)
        self.order.refresh_from_db();self.assertEqual(self.order.refund_summary,'failed')

    def test_legacy_preparing_order_stays_closed_after_artist_reverts_status(self):
        self.pay();self.item.artist_fulfillment_status='preparing';self.item.save()
        self.client.force_login(self.artist)
        self.client.post(reverse('artist_order_detail',args=[self.order.order_number]),{'status':'pending'})
        self.order.refresh_from_db();self.assertIsNotNone(self.order.preparation_started_at)
        self.assertFalse(self.order.can_buyer_cancel)


    def test_early_refund_event_can_recover_missing_local_refund_record(self):
        self.order.cancellation_requested_at=timezone.now();self.order.save()
        refund=Obj(id='re_recovered', payment_intent='pi_recovered', status='failed', metadata={'cancellation_reference':self.order.order_number})
        update_refund(refund)
        self.order.refresh_from_db()
        self.assertEqual(self.order.cancellation_refunds['pi_recovered']['id'],'re_recovered')
        self.assertEqual(self.order.refund_summary,'failed')
