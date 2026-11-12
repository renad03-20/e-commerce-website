from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from pages.models import SupportMessage


class ContactTests(TestCase):
    def details(self, **changes):
        data = {'name': 'Buyer', 'email': 'buyer@example.com', 'subject': 'order',
                'order_number': 'ART-TEST', 'message': 'Please help with my order.'}
        data.update(changes)
        return data

    def test_valid_public_message_is_saved_and_refresh_does_not_repeat_it(self):
        response = self.client.post(reverse('contact'), self.details(), follow=True)
        self.assertContains(response, 'Your message has been received.')
        saved = SupportMessage.objects.get()
        self.assertEqual(saved.message, self.details()['message'])
        self.assertEqual(saved.order_number, 'ART-TEST')
        self.assertFalse(saved.resolved)
        self.client.get(reverse('contact'))
        self.assertEqual(SupportMessage.objects.count(), 1)

    def test_invalid_fields_show_errors_and_keep_details_without_saving(self):
        for changes, field in [({'message': '   '}, 'message'), ({'email': 'bad'}, 'email'),
                               ({'subject': 'invalid'}, 'subject'), ({'name': ''}, 'name'),
                               ({'message': 'x' * 5001}, 'message')]:
            response = self.client.post(reverse('contact'), self.details(**changes))
            self.assertContains(response, 'Please correct the fields below.')
            self.assertIn(field, response.context['form'].errors)
        self.assertFalse(SupportMessage.objects.exists())

    def test_form_submits_to_server_and_contains_csrf_token(self):
        response = self.client.get(reverse('contact'))
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertNotContains(response, 'e.preventDefault()')
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('contact'), self.details()).status_code, 403)
        self.assertFalse(SupportMessage.objects.exists())

    def test_saved_messages_are_visible_only_to_authorized_staff(self):
        saved = SupportMessage.objects.create(**self.details())
        url = reverse('admin:pages_supportmessage_change', args=[saved.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        buyer = get_user_model().objects.create_user('support-buyer')
        self.client.force_login(buyer)
        self.assertEqual(self.client.get(url).status_code, 302)
        admin = get_user_model().objects.create_superuser('support-admin', 'admin@example.com', 'test-password')
        self.client.force_login(admin)
        response = self.client.get(url)
        self.assertContains(response, saved.message)

    def test_html_in_saved_message_is_escaped_in_admin(self):
        saved = SupportMessage.objects.create(**self.details(message='<script>alert(1)</script>'))
        admin = get_user_model().objects.create_superuser('support-admin', 'admin@example.com', 'test-password')
        self.client.force_login(admin)
        response = self.client.get(reverse('admin:pages_supportmessage_change', args=[saved.pk]))
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
