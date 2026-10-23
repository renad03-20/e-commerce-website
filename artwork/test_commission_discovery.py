from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import UserProfile
from artwork.models import Artwork, CustomRequest, CommissionStatusHistory


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CommissionDiscoveryTests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.buyer=User.objects.create_user('buyer',email='private-buyer@example.com',password='test-pass')
        self.other=User.objects.create_user('otherbuyer',password='test-pass')
        self.artist=User.objects.create_user('mira',email='private-artist@example.com',password='test-pass')
        self.artist.groups.add(Group.objects.get_or_create(name='Artists')[0])
        self.artist_profile=UserProfile.objects.create(user=self.artist,is_available_for_commissions=True,bio='Watercolor and botanical illustrations.',phone_number='PRIVATE-PHONE')
        UserProfile.objects.create(user=self.buyer)
        self.art=Artwork.objects.create(artist=self.artist,title='Botanical Study',description='A watercolor study.',price='40',stock=0,image='test-art.jpg')
        self.media=TemporaryDirectory();self.addCleanup(self.media.cleanup)
        settings=override_settings(MEDIA_ROOT=self.media.name);settings.enable();self.addCleanup(settings.disable)
        notify=patch('artwork.views._notify_commission');self.notify=notify.start();self.addCleanup(notify.stop)
        self.client.force_login(self.buyer)
        self.data={'title':'A custom landscape','requirements':'A landscape with mountains and a blue sky.','budget':'80.00'}

    def request_url(self,artist=None):return reverse('commission_request',args=[(artist or self.artist).pk])
    def profile_url(self,artist=None):return reverse('user_view_of_artist',args=[(artist or self.artist).pk])

    def test_public_directory_excludes_buyers_even_with_legacy_availability_flag(self):
        self.buyer.userprofile.is_available_for_commissions=True;self.buyer.userprofile.save()
        self.client.logout();response=self.client.get(reverse('artist_list'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,self.profile_url())
        self.assertNotContains(response,self.profile_url(self.buyer))
        self.assertContains(response,'Open for commissions')
        self.assertContains(response,'Botanical Study')

    def test_directory_omits_inactive_artists(self):
        self.artist.is_active=False;self.artist.save()
        response=self.client.get(reverse('artist_list'))
        self.assertNotContains(response,self.profile_url())
        self.assertContains(response,'No artists found')

    def test_search_and_open_filter(self):
        response=self.client.get(reverse('artist_list'),{'q':'MIR','open':'1'})
        self.assertContains(response,self.profile_url())
        self.artist_profile.is_available_for_commissions=False;self.artist_profile.save()
        response=self.client.get(reverse('artist_list'),{'q':'mira','open':'1'})
        self.assertContains(response,'No artists found')
        self.assertNotContains(response,self.profile_url())

    def test_public_profile_has_recipient_identity_portfolio_and_request_link(self):
        self.client.logout();response=self.client.get(self.profile_url())
        self.assertContains(response,'mira')
        self.assertContains(response,'Botanical Study')
        self.assertContains(response,'Sold out')
        self.assertContains(response,'Watercolor and botanical illustrations.')
        self.assertContains(response,self.request_url())
        self.assertNotContains(response,'private-artist@example.com')
        self.assertNotContains(response,'PRIVATE-PHONE')

    def test_profile_without_artworks_still_shows_artist_name_and_request_link(self):
        self.art.delete();response=self.client.get(self.profile_url())
        self.assertContains(response,'<h1>mira</h1>',html=True)
        self.assertContains(response,'This artist has not added artworks yet.')
        self.assertContains(response,self.request_url())

    def test_buyers_are_not_exposed_as_artist_profiles_or_request_recipients(self):
        self.buyer.userprofile.is_available_for_commissions=True;self.buyer.userprofile.save()
        for url in (self.profile_url(self.buyer),self.request_url(self.buyer)):
            response=self.client.get(url)
            self.assertRedirects(response,reverse('artist_list'))
        self.client.post(self.request_url(self.buyer),self.data)
        self.assertEqual(CustomRequest.objects.count(),0)

    def test_own_profile_has_manage_button_instead_of_self_request(self):
        self.client.force_login(self.artist);response=self.client.get(self.profile_url())
        self.assertContains(response,'Manage Commission Availability')
        self.assertNotContains(response,self.request_url())
        self.client.post(self.request_url(),self.data)
        self.assertEqual(CustomRequest.objects.count(),0)

    def test_guest_login_preserves_selected_artist_in_next_url(self):
        self.client.logout();response=self.client.get(self.request_url())
        self.assertEqual(response.status_code,302)
        self.assertIn('next='+self.request_url(),response.url)
        self.client.force_login(self.buyer);response=self.client.get(self.request_url())
        self.assertContains(response,'Sending your request to')
        self.assertContains(response,'Send Request to mira')

    def test_valid_request_is_bound_to_displayed_artist_and_logged_in_buyer(self):
        data=dict(self.data,receiver=self.other.pk,sender=self.artist.pk,artist_id=self.other.pk,status='completed',price='1')
        response=self.client.post(self.request_url(),data)
        commission=CustomRequest.objects.get()
        self.assertEqual(commission.receiver,self.artist)
        self.assertEqual(commission.sender,self.buyer)
        self.assertEqual(commission.status,'requested')
        self.assertIsNone(commission.price)
        self.assertRedirects(response,reverse('commission_detail',args=[commission.pk]))
        self.assertEqual(CommissionStatusHistory.objects.filter(commission=commission).count(),1)
        self.notify.assert_called_once()
        self.assertEqual(self.notify.call_args.kwargs['to_user'],self.artist)

    def test_invalid_form_keeps_recipient_and_typed_details(self):
        response=self.client.post(self.request_url(),{'title':'My saved title','requirements':''})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'My saved title')
        self.assertContains(response,'Your request has not been sent.')
        self.assertContains(response,'Send Request to mira')
        self.assertEqual(CustomRequest.objects.count(),0)

    def test_empty_post_shows_field_errors(self):
        response=self.client.post(self.request_url(),{})
        self.assertContains(response,'This field is required.',count=2)
        self.assertEqual(CustomRequest.objects.count(),0)

    def test_artist_closes_availability_before_submit(self):
        self.client.get(self.request_url())
        self.artist_profile.is_available_for_commissions=False;self.artist_profile.save()
        response=self.client.post(self.request_url(),self.data)
        self.assertContains(response,'Your request has not been sent.')
        self.assertContains(response,'A custom landscape')
        self.assertEqual(CustomRequest.objects.count(),0)
        self.notify.assert_not_called()

    def test_no_profile_means_commissions_closed(self):
        self.artist_profile.delete();response=self.client.get(self.request_url())
        self.assertContains(response,'not accepting new commissions')
        self.assertNotContains(response,'name="requirements"')
        self.client.post(self.request_url(),self.data)
        self.assertEqual(CustomRequest.objects.count(),0)

    def test_reference_image_upload(self):
        buffer=BytesIO();Image.new('RGB',(2,2),'white').save(buffer,format='PNG')
        image=SimpleUploadedFile('reference.png',buffer.getvalue(),content_type='image/png')
        self.client.post(self.request_url(),dict(self.data,reference_image=image))
        self.assertTrue(CustomRequest.objects.get().reference_image.name.endswith('.png'))

    def test_csrf_required_for_request_submission(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.buyer)
        self.assertEqual(client.post(self.request_url(),self.data).status_code,403)
        self.assertEqual(CustomRequest.objects.count(),0)

    def test_legacy_profile_submission_uses_same_authentication_and_recipient_checks(self):
        self.client.post(self.profile_url(),dict(self.data,submit_commission='1'))
        self.assertEqual(CustomRequest.objects.get().receiver,self.artist)
        self.client.logout();response=self.client.post(self.profile_url(),self.data)
        self.assertEqual(response.status_code,302)
        self.assertEqual(CustomRequest.objects.count(),1)

    def test_sold_out_artwork_keeps_artist_and_request_links(self):
        response=self.client.get(reverse('artwork_detail',args=[self.art.pk]))
        self.assertContains(response,'View Artist Portfolio')
        self.assertContains(response,self.profile_url())
        self.assertContains(response,self.request_url())

    def test_buyer_cannot_see_or_forge_commission_availability_setting(self):
        response=self.client.get(reverse('accounts:profile'))
        self.assertNotContains(response,'Open for Custom Commissions')
        self.assertNotContains(response,'Save Availability')
        self.client.post(reverse('accounts:profile'),{'update_commission':'1','is_available_for_commissions':'on'})
        self.buyer.userprofile.refresh_from_db()
        self.assertFalse(self.buyer.userprofile.is_available_for_commissions)

    def test_artist_can_manage_availability_and_directory_reflects_it(self):
        self.client.force_login(self.artist)
        response=self.client.get(reverse('accounts:profile'))
        self.assertContains(response,'Open for Custom Commissions')
        self.assertContains(response,'name="is_available_for_commissions"')
        self.client.post(reverse('accounts:profile'),{'update_commission':'1'})
        self.artist_profile.refresh_from_db();self.assertFalse(self.artist_profile.is_available_for_commissions)
        self.assertContains(self.client.get(self.profile_url()),'Commissions currently closed')

    def test_buyer_commissions_page_has_discovery_and_only_sent_section(self):
        response=self.client.get(reverse('commission_list'))
        self.assertContains(response,'Find an Artist')
        self.assertContains(response,'Requests You Sent')
        self.assertNotContains(response,'Requests For You')

    def test_buyer_cannot_accept_a_request_even_if_legacy_data_makes_them_receiver(self):
        commission=CustomRequest.objects.create(sender=self.other,receiver=self.buyer,title='Legacy request',requirements='Test')
        response=self.client.get(reverse('commission_detail',args=[commission.pk]))
        self.assertNotContains(response,'Accept &amp; Request Payment')
        self.assertNotContains(response,'<h3>Accept Request</h3>',html=True)
        self.client.post(reverse('commission_accept',args=[commission.pk]),{'price':'25'})
        commission.refresh_from_db();self.assertEqual(commission.status,'requested');self.assertIsNone(commission.accepted_at)

    def test_only_receiving_artist_can_accept(self):
        commission=CustomRequest.objects.create(sender=self.buyer,receiver=self.artist,title='Request',requirements='Test')
        self.client.post(reverse('commission_accept',args=[commission.pk]),{'price':'25'})
        commission.refresh_from_db();self.assertEqual(commission.status,'requested')
        self.client.force_login(self.artist)
        response=self.client.get(reverse('commission_detail',args=[commission.pk]))
        self.assertContains(response,'Accept &amp; Request Payment')
        self.client.post(reverse('commission_accept',args=[commission.pk]),{'price':'25'})
        commission.refresh_from_db();self.assertEqual(commission.status,'awaiting_payment')
        self.assertIsNotNone(commission.accepted_at)

    def test_artist_role_does_not_allow_accepting_another_artists_request(self):
        commission=CustomRequest.objects.create(sender=self.buyer,receiver=self.artist,title='Request',requirements='Test')
        self.other.groups.add(Group.objects.get(name='Artists'));self.client.force_login(self.other)
        self.client.post(reverse('commission_accept',args=[commission.pk]),{'price':'25'})
        commission.refresh_from_db();self.assertEqual(commission.status,'requested')

    def test_accept_requires_post(self):
        commission=CustomRequest.objects.create(sender=self.buyer,receiver=self.artist,title='Request',requirements='Test')
        self.client.force_login(self.artist)
        self.assertEqual(self.client.get(reverse('commission_accept',args=[commission.pk])).status_code,405)
        commission.refresh_from_db();self.assertEqual(commission.status,'requested')

    def test_buyer_legacy_receiver_cannot_start_deliver_or_decline(self):
        commission=CustomRequest.objects.create(sender=self.other,receiver=self.buyer,title='Legacy request',requirements='Test')
        for route in ('commission_start_work','commission_decline','commission_delivery'):
            self.client.post(reverse(route,args=[commission.pk]),{'reason_for_declined':'No','external_link':'https://example.com/work'})
            commission.refresh_from_db();self.assertEqual(commission.status,'requested')
        self.assertEqual(commission.deliveries.count(),0)

    def test_artist_buying_from_another_artist_sees_only_buyer_controls(self):
        self.other.groups.add(Group.objects.get(name='Artists'))
        commission=CustomRequest.objects.create(sender=self.other,receiver=self.artist,title='Request',requirements='Test')
        self.client.force_login(self.other)
        response=self.client.get(reverse('commission_detail',args=[commission.pk]))
        self.assertNotContains(response,'<h3>Accept Request</h3>',html=True)
        self.assertContains(response,reverse('artist_dashboard'))

    def test_directory_does_not_duplicate_artists_with_multiple_group_memberships(self):
        group=Group.objects.create(name='Other Group');self.artist.groups.add(group)
        response=self.client.get(reverse('artist_list'))
        self.assertEqual(response.context['page_obj'].paginator.count,1)
        self.assertEqual(len(response.context['page_obj'].object_list[0].portfolio_preview),1)


    def test_directory_pagination_and_portfolio_preview_limit(self):
        User=get_user_model()
        for index in range(12):
            artist=User.objects.create_user(f'artist{index:02d}')
            artist.groups.add(Group.objects.get(name='Artists'))
        for index in range(4):
            Artwork.objects.create(artist=self.artist,title=f'Extra work {index}',price='10',image='test.jpg')
        first=self.client.get(reverse('artist_list'))
        second=self.client.get(reverse('artist_list'),{'page':2})
        self.assertEqual(first.context['page_obj'].paginator.count,13)
        self.assertEqual(len(first.context['page_obj']),12)
        self.assertEqual(len(second.context['page_obj']),1)
        self.assertEqual(len(second.context['page_obj'].object_list[0].portfolio_preview),3)
