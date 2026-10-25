from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from artwork.models import CustomRequest, CommissionRevisionRequest, CommissionStatusHistory


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CommissionCompletionTests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.buyer=User.objects.create_user('completionbuyer',password='test-pass')
        self.artist=User.objects.create_user('completionartist',password='test-pass')
        self.artist.groups.add(Group.objects.get_or_create(name='Artists')[0])
        self.other=User.objects.create_user('completionother',password='test-pass')
        self.commission=CustomRequest.objects.create(sender=self.buyer,receiver=self.artist,title='A painting',requirements='Test',status='delivered',paid_at=timezone.now(),work_started_at=timezone.now())
        self.client.force_login(self.buyer)
        patcher=patch('artwork.views._notify_commission');self.notify=patcher.start();self.addCleanup(patcher.stop)

    def complete_url(self):return reverse('commission_mark_complete',args=[self.commission.pk])
    def revision_url(self):return reverse('commission_revision_request',args=[self.commission.pk])

    def test_get_does_not_complete_or_create_revision(self):
        for url in (self.complete_url(),self.revision_url()):
            self.assertEqual(self.client.get(url).status_code,405)
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.status,'delivered')
        self.assertIsNone(self.commission.completed_at)
        self.assertEqual(self.commission.revisions.count(),0)
        self.notify.assert_not_called()

    def test_buyer_approves_once_and_notification_waits_for_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(self.complete_url())
            self.notify.assert_not_called()
        self.assertEqual(response.status_code,302)
        self.commission.refresh_from_db();completed_at=self.commission.completed_at
        self.assertEqual(self.commission.status,'completed');self.assertIsNotNone(completed_at)
        self.notify.assert_called_once()
        with self.captureOnCommitCallbacks(execute=True):self.client.post(self.complete_url())
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.completed_at,completed_at)
        self.assertEqual(CommissionStatusHistory.objects.filter(commission=self.commission,to_status='completed').count(),1)
        self.assertEqual(self.notify.call_count,1)

    def test_artist_and_other_buyer_cannot_approve_or_request_revision(self):
        for user in (self.artist,self.other):
            self.client.force_login(user)
            self.client.post(self.complete_url())
            self.client.post(self.revision_url(),{'message':'A change'})
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.status,'delivered');self.assertIsNone(self.commission.completed_at)
        self.assertEqual(self.commission.revisions.count(),0)

    def test_login_and_csrf_required(self):
        self.client.logout()
        self.assertEqual(self.client.post(self.complete_url()).status_code,302)
        client=Client(enforce_csrf_checks=True);client.force_login(self.buyer)
        self.assertEqual(client.post(self.complete_url()).status_code,403)
        self.assertEqual(client.post(self.revision_url(),{'message':'A change'}).status_code,403)
        self.commission.refresh_from_db();self.assertEqual(self.commission.status,'delivered')

    def test_approval_rejected_before_delivery(self):
        self.commission.status='in_progress';self.commission.save()
        self.client.post(self.complete_url())
        self.commission.refresh_from_db();self.assertEqual(self.commission.status,'in_progress')
        self.assertIsNone(self.commission.completed_at)

    def test_unpaid_and_cancellation_in_progress_reject_both_actions(self):
        self.commission.paid_at=None;self.commission.save()
        self.client.post(self.complete_url());self.client.post(self.revision_url(),{'message':'A change'})
        self.commission.refresh_from_db();self.assertEqual(self.commission.status,'delivered')
        self.commission.paid_at=timezone.now();self.commission.cancellation_requested_at=timezone.now();self.commission.save()
        self.client.post(self.complete_url());self.client.post(self.revision_url(),{'message':'A change'})
        self.commission.refresh_from_db();self.assertIsNone(self.commission.completed_at)
        self.assertEqual(self.commission.revisions.count(),0)

    def test_revision_limit_enforced_on_post_after_delivery(self):
        self.commission.revision_count=2;self.commission.save()
        response=self.client.post(self.revision_url(),{'message':'An extra revision'})
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.status,'delivered');self.assertEqual(self.commission.revision_count,2)
        self.assertEqual(self.commission.revisions.count(),0)
        from django.contrib.messages import get_messages
        self.assertTrue(any('revision limit' in str(m) for m in get_messages(response.wsgi_request)))

    def test_pending_revision_blocks_approval_and_duplicate_request(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.revision_url(),{'message':'Please lighten the background'})
        self.client.post(self.complete_url());self.client.post(self.revision_url(),{'message':'A duplicate request'})
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.status,'revision_requested');self.assertEqual(self.commission.revision_count,1)
        self.assertIsNone(self.commission.completed_at);self.assertEqual(self.commission.revisions.count(),1)

    def test_unresolved_revision_blocks_approval_even_with_delivered_status(self):
        revision=CommissionRevisionRequest.objects.create(commission=self.commission,requested_by=self.buyer,message='Still pending')
        self.client.post(self.complete_url());self.commission.refresh_from_db();self.assertIsNone(self.commission.completed_at)
        revision.resolved_at=timezone.now();revision.save()
        self.client.post(self.complete_url());self.commission.refresh_from_db();self.assertEqual(self.commission.status,'completed')

    def test_completed_commission_rejects_revision_and_hides_actions(self):
        self.client.post(self.complete_url());self.client.post(self.revision_url(),{'message':'Too late'})
        self.commission.refresh_from_db();self.assertEqual(self.commission.status,'completed')
        self.assertEqual(self.commission.revisions.count(),0)
        response=self.client.get(reverse('commission_detail',args=[self.commission.pk]))
        self.assertNotContains(response,'>Mark Complete</button>')
        self.assertNotContains(response,'>Request Revision</button>')
