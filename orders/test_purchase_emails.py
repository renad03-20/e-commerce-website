from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.template import TemplateDoesNotExist
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from artwork.models import Artwork
from cart.models import Cart, CartItem
from orders.emails import send_artist_order_notification, send_order_confirmation
from orders.models import Order, OrderItem


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='Artsy <shop@example.com>',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
class PurchaseEmailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.buyer = User.objects.create_user('email-buyer', email='buyer@example.com')
        self.artist = User.objects.create_user('email-artist', email='artist@example.com')
        self.other = User.objects.create_user('other-artist', email='other-artist@example.com')
        self.art = Artwork.objects.create(artist=self.artist, title='Charcoal portrait', price='20.00', stock=3, image='portrait.jpg')
        self.order = Order.objects.create(
            user=self.buyer, first_name='Buyer', last_name='Test', email=self.buyer.email,
            address='Buyer shipping street', city='Jeddah', postal_code='12345', country='SA',
            paid=True, status='processing', artist_notes='PRIVATE PACKING NOTE',
        )
        self.item = OrderItem.objects.create(order=self.order, artwork=self.art, price='20.00', quantity=1)
        self.client.force_login(self.buyer)
        session = self.client.session;session['order_id'] = self.order.order_number;session.save()
        self.url = reverse('payment_completed')
        self.origin = 'http://127.0.0.1:8001/'

    def html(self, message):
        return message.alternatives[0].content

    def test_buyer_confirmation_has_correct_recipient_reference_and_grand_total(self):
        self.assertTrue(send_order_confirmation(self.order, site_url=self.origin))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.buyer.email])
        self.assertEqual(message.from_email, 'Artsy <shop@example.com>')
        self.assertIn(self.order.order_number, message.subject)
        self.assertIn('Quantity: 1', message.body)
        self.assertIn('Subtotal: USD 20.00', message.body)
        self.assertIn('Tax (8%): USD 1.60', message.body)
        self.assertIn('Shipping: USD 10.00', message.body)
        self.assertIn('TOTAL PAID: USD 31.60', message.body)
        self.assertIn('Buyer shipping street', message.body)
        self.assertIn('USD 31.60', self.html(message))
        self.assertNotIn('PRIVATE PACKING NOTE', message.body + self.html(message))

    def test_multipart_email_has_readable_plain_text_and_one_html_alternative(self):
        send_order_confirmation(self.order, site_url=self.origin)
        message = mail.outbox[0]
        self.assertNotIn('<style', message.body)
        self.assertNotIn('<table', message.body)
        self.assertEqual(len(message.alternatives), 1)
        self.assertEqual(message.alternatives[0].mimetype, 'text/html')

    def test_artist_receives_only_their_purchased_artwork_and_amount(self):
        other_art = Artwork.objects.create(artist=self.other, title='OTHER ARTIST PRIVATE TITLE', price='50', stock=2, image='other.jpg')
        OrderItem.objects.create(order=self.order, artwork=other_art, price='50')
        self.assertTrue(send_artist_order_notification(self.item, site_url=self.origin))
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.artist.email])
        self.assertIn(self.order.order_number, message.subject)
        self.assertIn('Charcoal portrait', message.body)
        self.assertIn('Artwork amount: USD 20.00', message.body)
        self.assertNotIn('OTHER ARTIST PRIVATE TITLE', message.body + self.html(message))
        self.assertNotIn('PRIVATE PACKING NOTE', message.body + self.html(message))
        self.assertNotIn(self.other.email, str(message.to))

    def test_request_origin_is_used_for_buyer_and_artist_links(self):
        self.client.get(self.url, HTTP_HOST='127.0.0.1:8001')
        buyer_url = self.origin.rstrip('/') + reverse('order_detail', args=[self.order.order_number])
        artist_url = self.origin.rstrip('/') + reverse('artist_order_detail', args=[self.order.order_number])
        self.assertIn(buyer_url, mail.outbox[0].body)
        self.assertIn(artist_url, mail.outbox[1].body)
        self.assertNotIn('localhost:8000', mail.outbox[0].body + mail.outbox[1].body)

    def test_https_site_link_is_not_downgraded_or_double_prefixed(self):
        send_order_confirmation(self.order, site_url='https://art.example.com/')
        self.assertIn('https://art.example.com/orders/', mail.outbox[0].body)
        self.assertNotIn('http://https:', mail.outbox[0].body)

    def test_standalone_helpers_support_site_domain_configuration(self):
        with patch('orders.emails.config', return_value='https://configured.example.com'):
            self.assertTrue(send_order_confirmation(self.order))
        self.assertIn('https://configured.example.com/orders/', mail.outbox[0].body)

    def test_unpaid_orders_do_not_send_payment_confirmations(self):
        self.order.paid = False;self.order.save()
        self.assertFalse(send_order_confirmation(self.order, site_url=self.origin))
        self.assertFalse(send_artist_order_notification(self.item, site_url=self.origin))
        self.assertEqual(len(mail.outbox), 0)

    def test_cancelled_or_cancelling_orders_do_not_send_payment_confirmations(self):
        for state in ('cancelled', 'cancelling'):
            self.order.status = 'cancelled' if state == 'cancelled' else 'processing'
            self.order.cancellation_requested_at = timezone.now() if state == 'cancelling' else None
            self.order.save()
            self.assertFalse(send_order_confirmation(self.order, site_url=self.origin))
            self.assertFalse(send_artist_order_notification(self.item, site_url=self.origin))
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_email_template_is_logged_as_a_failure(self):
        with patch('orders.emails.render_to_string', side_effect=TemplateDoesNotExist('example')):
            with self.assertLogs('orders.emails', level='ERROR'):
                self.assertFalse(send_order_confirmation(self.order, site_url=self.origin))
        self.assertEqual(len(mail.outbox), 0)

    def test_mail_transport_exception_is_logged_as_a_failure(self):
        with patch('orders.emails.EmailMultiAlternatives.send', side_effect=OSError('test mail transport failure')):
            with self.assertLogs('orders.emails', level='ERROR'):
                self.assertFalse(send_artist_order_notification(self.item, site_url=self.origin))

    def test_backend_returning_zero_is_not_reported_as_sent(self):
        with patch('orders.emails.EmailMultiAlternatives.send', return_value=0):
            with self.assertLogs('orders.emails', level='ERROR'):
                self.assertFalse(send_order_confirmation(self.order, site_url=self.origin))

    def test_invalid_recipient_is_logged_and_no_message_is_sent(self):
        self.order.email = ''
        with self.assertLogs('orders.emails', level='ERROR'):
            self.assertFalse(send_order_confirmation(self.order, site_url=self.origin))
        self.assertEqual(len(mail.outbox), 0)

    def test_html_escapes_user_supplied_names_and_titles(self):
        self.order.first_name = '<script>alert(1)</script>'
        self.item.artwork_title = '<b>My portrait</b>';self.item.save()
        send_order_confirmation(self.order, site_url=self.origin)
        html = self.html(mail.outbox[0])
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('&lt;b&gt;My portrait&lt;/b&gt;', html)
        self.assertNotIn('<script>alert', html)
        self.assertIn('<b>My portrait</b>', mail.outbox[0].body)

    def test_payment_return_sends_one_of_each_and_refresh_does_not_repeat(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('order_created', args=[self.order.order_number]))
        self.assertEqual(len(mail.outbox), 2)
        for unused in range(2):
            self.client.get(response.url)
        self.client.get(self.url)
        self.assertEqual(len(mail.outbox), 2)
        self.assertNotIn('order_id', self.client.session)
        self.art.refresh_from_db();self.assertEqual(self.art.stock, 3)
        self.order.refresh_from_db();self.assertTrue(self.order.paid)

    def test_failed_buyer_email_does_not_block_the_artist_notification(self):
        original_send = __import__('django.core.mail', fromlist=['EmailMultiAlternatives']).EmailMultiAlternatives.send
        def send(message, *args, **kwargs):
            if message.to == [self.buyer.email]:
                raise OSError('buyer mail transport test failure')
            return original_send(message, *args, **kwargs)
        with patch('orders.emails.EmailMultiAlternatives.send', autospec=True, side_effect=send):
            with self.assertLogs('orders.emails', level='ERROR'):
                response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.artist.email])

    def test_wrong_buyer_cannot_trigger_another_orders_purchase_emails(self):
        self.client.force_login(self.other)
        session=self.client.session;session['order_id']=self.order.order_number;session.save()
        response=self.client.get(self.url)
        self.assertRedirects(response, reverse('order_list'))
        self.assertEqual(len(mail.outbox), 0)

    def test_unpaid_return_preserves_cart_and_sends_no_email(self):
        self.order.paid=False;self.order.status='pending';self.order.save()
        cart=Cart.objects.create(user=self.buyer)
        CartItem.objects.create(cart=cart, artwork=self.art, quantity=1)
        response=self.client.get(self.url)
        self.assertRedirects(response, reverse('order_detail', args=[self.order.order_number]))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(cart.items.count(), 1)

    def test_confirmation_page_does_not_claim_an_email_was_sent(self):
        response=self.client.get(reverse('order_created', args=[self.order.order_number]))
        self.assertNotContains(response, "We&#x27;ve sent a confirmation email")
        self.assertNotContains(response, "We've sent a confirmation email")
        self.assertContains(response, self.order.email)
        self.assertEqual(len(mail.outbox), 0)
