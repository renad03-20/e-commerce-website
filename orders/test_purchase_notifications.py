import hashlib
import hmac
import json
import time
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from artwork.models import Artwork
from orders.models import Order, OrderItem, PurchaseEmailJob
from orders.purchase_notifications import deliver_due_purchase_emails

State = PurchaseEmailJob.State


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    STRIPE_WEBHOOK_SECRET='whsec_isolated_test_only',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
class PurchaseNotificationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.buyer = User.objects.create_user('queue-buyer', email='buyer@example.com')
        self.artist = User.objects.create_user('queue-artist', email='artist@example.com')
        self.art = Artwork.objects.create(artist=self.artist, title='Painting', price='20.00', stock=3, image='painting.jpg')
        self.order = Order.objects.create(user=self.buyer, email=self.buyer.email)
        self.item = OrderItem.objects.create(order=self.order, artwork=self.art, price='20.00', quantity=1)

    def post_webhook(self, event_type='checkout.session.completed', event_id='evt_test_purchase',
                     signature=None, **overrides):
        session = {
            'object': 'checkout.session', 'id': 'cs_test_purchase', 'payment_status': 'paid',
            'client_reference_id': self.order.order_number, 'payment_intent': 'pi_test_purchase',
            'amount_total': int(self.order.get_grand_total() * 100), 'currency': 'usd',
        }
        session.update(overrides)
        payload = json.dumps({'object': 'event', 'id': event_id, 'type': event_type,
                              'data': {'object': session}})
        timestamp = int(time.time())
        digest = hmac.new(settings.STRIPE_WEBHOOK_SECRET.encode(),
                          f'{timestamp}.{payload}'.encode(), hashlib.sha256).hexdigest()
        return self.client.post(reverse('stripe_webhook'), data=payload,
                                content_type='application/json',
                                HTTP_STRIPE_SIGNATURE=signature or f't={timestamp},v1={digest}')

    def assert_stock(self, quantity):
        self.art.refresh_from_db()
        self.assertEqual(self.art.stock, quantity)

    def test_verified_payment_queues_and_worker_sends_without_browser_return(self):
        self.assertEqual(self.post_webhook().status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.paid)
        self.assert_stock(2)
        self.assertEqual(PurchaseEmailJob.objects.filter(state=State.PENDING).count(), 2)
        self.assertEqual(len(mail.outbox), 0)
        with patch('orders.emails.config', return_value='https://art.example.com'):
            self.assertEqual(deliver_due_purchase_emails()[State.SENT], 2)
        self.assertCountEqual([msg.to for msg in mail.outbox], [[self.buyer.email], [self.artist.email]])
        self.assertTrue(all('https://art.example.com/orders/' in msg.body for msg in mail.outbox))
        self.assertEqual(PurchaseEmailJob.objects.filter(state=State.SENT, sent_at__isnull=False).count(), 2)

    def test_replayed_event_and_second_event_type_do_not_repeat_stock_or_emails(self):
        self.assertEqual(self.post_webhook().status_code, 200)
        self.assertEqual(self.post_webhook().status_code, 200)
        deliver_due_purchase_emails()
        self.assertEqual(self.post_webhook('checkout.session.async_payment_succeeded', 'evt_another').status_code, 200)
        self.assertFalse(deliver_due_purchase_emails())
        self.assertEqual(PurchaseEmailJob.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assert_stock(2)

    def test_invalid_signature_and_unpaid_event_never_queue(self):
        self.assertEqual(self.post_webhook(signature='t=0,v1=invalid').status_code, 400)
        self.assertEqual(self.post_webhook(payment_status='unpaid').status_code, 200)
        self.assertFalse(PurchaseEmailJob.objects.exists())
        self.assert_stock(3)

    def test_queue_failure_rolls_back_payment_and_stock(self):
        with patch('orders.purchase_notifications.PurchaseEmailJob.objects.bulk_create',
                   side_effect=RuntimeError('test queue write failure')):
            with self.assertLogs('orders.views', level='ERROR'):
                self.assertEqual(self.post_webhook().status_code, 500)
        self.order.refresh_from_db()
        self.assertFalse(self.order.paid)
        self.assert_stock(3)
        self.assertFalse(PurchaseEmailJob.objects.exists())
        self.assertEqual(self.post_webhook().status_code, 200)
        self.assertEqual(PurchaseEmailJob.objects.count(), 2)
        self.assert_stock(2)

    def test_prior_paid_order_is_not_queued_on_replay_after_upgrade(self):
        self.order.paid = True
        self.order.stripe_payment_intent_id = 'pi_test_purchase'
        self.order.save()
        self.assertEqual(self.post_webhook().status_code, 200)
        self.assertFalse(PurchaseEmailJob.objects.exists())
        self.assert_stock(3)

    def test_worker_retries_only_the_failed_message(self):
        self.assertEqual(self.post_webhook().status_code, 200)
        with patch('orders.purchase_notifications.send_order_confirmation', return_value=False):
            results = deliver_due_purchase_emails()
        self.assertEqual(results[State.SENT], 1)
        self.assertEqual(results[State.PENDING], 1)
        self.assertEqual(mail.outbox[0].to, [self.artist.email])
        job = PurchaseEmailJob.objects.get(item__isnull=True)
        self.assertEqual(job.attempts, 1)
        self.assertGreater(job.available_at, timezone.now())
        self.assertFalse(deliver_due_purchase_emails())
        PurchaseEmailJob.objects.filter(pk=job.pk).update(available_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(deliver_due_purchase_emails()[State.SENT], 1)
        self.assertEqual(mail.outbox[1].to, [self.buyer.email])
        self.assertFalse(deliver_due_purchase_emails())

    def test_claimed_job_is_not_taken_by_another_worker(self):
        self.assertEqual(self.post_webhook().status_code, 200)
        def competing_worker(order):
            self.assertEqual(deliver_due_purchase_emails()[State.SENT], 1)
            return True
        with patch('orders.purchase_notifications.send_order_confirmation', side_effect=competing_worker) as send:
            deliver_due_purchase_emails()
        send.assert_called_once()
        self.assertEqual(PurchaseEmailJob.objects.filter(state=State.SENT).count(), 2)

    def test_cancelled_order_is_skipped_before_dispatch(self):
        self.assertEqual(self.post_webhook().status_code, 200)
        self.order.status = 'cancelled'
        self.order.save()
        self.assertEqual(deliver_due_purchase_emails()[State.SKIPPED], 2)
        self.assertEqual(len(mail.outbox), 0)

    def test_reassigned_artwork_does_not_disclose_order_to_new_artist(self):
        self.assertEqual(self.post_webhook().status_code, 200)
        self.art.artist = self.buyer
        self.art.save()
        results = deliver_due_purchase_emails()
        self.assertEqual(results[State.SKIPPED], 1)
        self.assertEqual(results[State.SENT], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Order confirmation', mail.outbox[0].subject)

    def test_retry_limit_and_explicit_command_recovery(self):
        self.assertEqual(self.post_webhook().status_code, 200)
        job = PurchaseEmailJob.objects.get(item__isnull=True)
        PurchaseEmailJob.objects.filter(pk=job.pk).update(attempts=4)
        with patch('orders.purchase_notifications.send_order_confirmation', return_value=False):
            self.assertEqual(deliver_due_purchase_emails()[State.FAILED], 1)
        output = StringIO()
        call_command('process_purchase_emails', '--status', stdout=output)
        self.assertIn('failed: 1', output.getvalue())
        call_command('process_purchase_emails', '--retry-job', str(job.pk), stdout=output)
        call_command('process_purchase_emails', stdout=output)
        job.refresh_from_db()
        self.assertEqual(job.state, State.SENT)
        self.assertEqual(job.attempts, 1)
        self.assertEqual(len(mail.outbox), 2)
