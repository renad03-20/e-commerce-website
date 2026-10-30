from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import UserProfile
from artwork.forms import CommissionRequestForm
from artwork.models import CustomRequest, CommissionStatusHistory


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CommissionRequestValidationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.buyer = User.objects.create_user('validation-buyer')
        self.artist = User.objects.create_user('validation-artist')
        self.artist.groups.add(Group.objects.get_or_create(name='Artists')[0])
        UserProfile.objects.create(user=self.artist, is_available_for_commissions=True)
        self.url = reverse('commission_request', args=[self.artist.pk])
        self.client.force_login(self.buyer)
        clock = patch('artwork.forms.timezone.localdate', return_value=date(2026, 10, 29))
        self.today = clock.start().return_value
        self.addCleanup(clock.stop)
        notification = patch('artwork.views._notify_commission')
        self.notify = notification.start()
        self.addCleanup(notification.stop)
        self.data = {
            'title': 'A charcoal portrait',
            'requirements': 'A portrait with a dark background.',
            'budget': '100.00',
            'desired_deadline': (self.today + timedelta(days=30)).isoformat(),
        }

    def assert_rejected(self, data, fields):
        # Direct POST bypasses browser required/min attributes.
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your request has not been sent.')
        self.assertEqual(set(response.context['form'].errors), set(fields))
        self.assertFalse(CustomRequest.objects.exists())
        self.assertFalse(CommissionStatusHistory.objects.exists())
        self.notify.assert_not_called()
        return response

    def test_empty_required_fields_have_visible_explanations_and_error_links(self):
        response = self.assert_rejected({}, ['title', 'requirements'])
        self.assertContains(response, 'Enter a request title.')
        self.assertContains(response, 'Describe what you would like the artist to create.')
        self.assertContains(response, 'href="#id_title"')
        self.assertContains(response, 'href="#id_requirements"')
        self.assertContains(response, 'novalidate')

    def test_whitespace_only_required_fields_are_rejected(self):
        self.assert_rejected(dict(self.data, title='   ', requirements='\n\t '), ['title', 'requirements'])

    def test_yesterday_is_rejected_and_buyer_details_are_preserved(self):
        response = self.assert_rejected(
            dict(self.data, desired_deadline=(self.today - timedelta(days=1)).isoformat()),
            ['desired_deadline'],
        )
        self.assertContains(response, 'Choose today or a later date for your preferred deadline.')
        self.assertContains(response, self.data['title'])
        self.assertContains(response, self.data['requirements'])
        self.assertContains(response, 'Send Request to validation-artist')

    def test_ancient_year_from_reported_example_is_rejected(self):
        self.assert_rejected(dict(self.data, desired_deadline='0007-01-27'), ['desired_deadline'])

    def test_negative_budget_is_rejected(self):
        for budget in ('-0.01', '-100.00'):
            with self.subTest(budget=budget):
                response = self.assert_rejected(dict(self.data, budget=budget), ['budget'])
                self.assertContains(response, 'Your budget must be greater than zero.')

    def test_both_invalid_optional_fields_show_errors(self):
        self.assert_rejected(dict(self.data, budget='-1', desired_deadline='2000-01-01'), ['budget', 'desired_deadline'])

    def test_invalid_date_is_rejected(self):
        self.assert_rejected(dict(self.data, desired_deadline='2026-02-30'), ['desired_deadline'])

    def test_invalid_and_nonfinite_budgets_are_rejected(self):
        for budget in ('not a number', 'NaN', 'Infinity'):
            with self.subTest(budget=budget):
                self.assert_rejected(dict(self.data, budget=budget), ['budget'])

    def test_optional_budget_and_deadline_can_be_left_blank(self):
        response = self.client.post(self.url, dict(self.data, budget='', desired_deadline=''))
        commission = CustomRequest.objects.get()
        self.assertRedirects(response, reverse('commission_detail', args=[commission.pk]))
        self.assertIsNone(commission.budget)
        self.assertIsNone(commission.desired_deadline)

    def test_today_is_an_allowed_deadline(self):
        response = self.client.post(self.url, dict(self.data, desired_deadline=self.today.isoformat()))
        commission = CustomRequest.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(commission.desired_deadline, self.today)

    def test_zero_budget_is_rejected(self):
        response = self.assert_rejected(
            dict(self.data, budget='0'), ['budget']
        )
        self.assertContains(response, 'Your budget must be greater than zero.')

    def test_future_deadline_and_positive_budget_create_one_request(self):
        response = self.client.post(self.url, self.data)
        commission = CustomRequest.objects.get()
        self.assertRedirects(response, reverse('commission_detail', args=[commission.pk]))
        self.assertEqual(commission.budget, Decimal('100.00'))
        self.assertEqual(commission.desired_deadline.isoformat(), self.data['desired_deadline'])
        self.assertEqual(commission.sender, self.buyer)
        self.assertEqual(commission.receiver, self.artist)
        self.assertEqual(commission.status, CustomRequest.STATUS_REQUESTED)
        self.assertEqual(CommissionStatusHistory.objects.count(), 1)
        self.notify.assert_called_once()
        self.client.get(response.url)
        self.assertEqual(CustomRequest.objects.count(), 1)

    def test_legacy_portfolio_post_cannot_bypass_validation(self):
        self.url = reverse('user_view_of_artist', args=[self.artist.pk])
        self.assert_rejected(dict(self.data, budget='-1'), ['budget'])

    def test_date_hint_uses_current_local_date_for_each_form(self):
        self.assertEqual(CommissionRequestForm().fields['desired_deadline'].widget.attrs['min'], '2026-10-29')
        with patch('artwork.forms.timezone.localdate', return_value=date(2026, 10, 30)):
            self.assertEqual(CommissionRequestForm().fields['desired_deadline'].widget.attrs['min'], '2026-10-30')
