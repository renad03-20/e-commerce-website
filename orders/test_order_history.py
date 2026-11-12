from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from orders.models import Order


class HistoryLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        if tag == 'a':
            self.links.append(dict(attributes).get('href'))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class BuyerOrderHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.buyer = User.objects.create_user('history-buyer')
        self.other = User.objects.create_user('other-history-buyer')
        self.empty_buyer = User.objects.create_user('empty-history-buyer')
        self.first = Order.objects.create(user=self.buyer, order_number='ART-HISTORY-FIRST')
        self.second = Order.objects.create(user=self.buyer, order_number='ART-HISTORY-SECOND')
        self.unrelated = Order.objects.create(user=self.other, order_number='ART-OTHER-PRIVATE')
        self.client.force_login(self.buyer)

    def test_back_to_orders_renders_existing_orders(self):
        account_page = self.client.get(reverse('accounts:order_history'))
        detail_url = reverse('order_detail', args=[self.first.order_number])
        self.assertIn(detail_url, HistoryLinks(account_page.content.decode()).links)
        detail = self.client.get(detail_url)
        history_url = reverse('order_list')
        self.assertIn(history_url, HistoryLinks(detail.content.decode()).links)
        response = self.client.get(history_url)
        self.assertContains(response, self.first.order_number)
        self.assertContains(response, self.second.order_number)
        self.assertNotContains(response, 'No Orders Yet')
        self.assertNotContains(response, self.unrelated.order_number)

    def test_both_history_routes_use_only_the_signed_in_buyers_orders(self):
        for name in ('order_list', 'accounts:order_history'):
            response = self.client.get(reverse(name))
            self.assertEqual(set(response.context['orders']), {self.first, self.second})
            self.assertNotContains(response, self.unrelated.order_number)

    def test_empty_history_still_shows_the_empty_state(self):
        self.client.force_login(self.empty_buyer)
        for name in ('order_list', 'accounts:order_history'):
            response = self.client.get(reverse(name))
            self.assertContains(response, 'No Orders Yet')
            self.assertNotContains(response, self.first.order_number)

    def test_both_history_routes_require_login(self):
        self.client.logout()
        for name in ('order_list', 'accounts:order_history'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn('next=', response.url)

    def test_denied_order_detail_returns_to_a_working_own_history(self):
        response = self.client.get(reverse('order_detail', args=[self.unrelated.order_number]), follow=True)
        self.assertContains(response, self.first.order_number)
        self.assertContains(response, self.second.order_number)
        self.assertContains(response, "You don&#x27;t have permission to view this order.")
        self.assertNotContains(response, self.unrelated.order_number)

    def test_history_has_no_all_buyers_debug_queryset(self):
        response = self.client.get(reverse('order_list'))
        self.assertNotIn('orders2', response.context)
