from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import shutil

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.management import call_command, CommandError
from django.http import HttpResponse
from django.test import TestCase, override_settings, modify_settings
from django.urls import include, path, re_path, reverse
from django.views.static import serve
from PIL import Image

from artwork.checks import check_private_commission_root
from artwork.models import CustomRequest, CommissionMessage, CommissionDelivery, Artwork
from artwork.private_storage import PrivateCommissionStorage


def public_media_for_test(request, path):
    return serve(request, path, document_root=settings.MEDIA_ROOT)

# Exercise the same otherwise-public development media handler that exposed files.
urlpatterns = [path('', include('storefront.urls')), re_path(r'^media/(?P<path>.*)$', public_media_for_test)]


@override_settings(ROOT_URLCONF=__name__, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], SECURE_SSL_REDIRECT=False)
@modify_settings(MIDDLEWARE={'prepend': 'artwork.private_files.LegacyCommissionMediaGuard'})
class PrivateCommissionFileTests(TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.public=Path(self.directory.name)/'public'
        self.private=Path(self.directory.name)/'private'
        config=override_settings(MEDIA_ROOT=str(self.public), PRIVATE_MEDIA_ROOT=str(self.private), MEDIA_URL='/media/')
        config.enable();self.addCleanup(config.disable)
        User=get_user_model()
        self.buyer=User.objects.create_user('filebuyer',password='test-pass')
        self.artist=User.objects.create_user('fileartist',password='test-pass')
        self.other_buyer=User.objects.create_user('otherfilebuyer',password='test-pass')
        self.other_artist=User.objects.create_user('otherfileartist',password='test-pass')
        self.staff=User.objects.create_superuser('filestaff',email='test@example.com',password='test-pass')
        artists=Group.objects.get_or_create(name='Artists')[0]
        self.artist.groups.add(artists);self.other_artist.groups.add(artists)
        image=BytesIO();Image.new('RGB',(2,2),'white').save(image,format='PNG');self.image=image.getvalue()
        self.commission=CustomRequest.objects.create(sender=self.buyer,receiver=self.artist,title='Private request',requirements='Test',reference_image=ContentFile(self.image,name='reference.png'))
        self.message=CommissionMessage.objects.create(commission=self.commission,sender=self.buyer,body='Private note',attachment=ContentFile(b'private attachment',name='notes.txt'))
        self.delivery=CommissionDelivery.objects.create(commission=self.commission,delivered_by=self.artist,delivery_file=ContentFile(b'private delivery',name='drawing.txt'))
        self.fields=[self.commission.reference_image,self.message.attachment,self.delivery.delivery_file]
        self.contents=[self.image,b'private attachment',b'private delivery']
        self.client.force_login(self.buyer)

    def bytes(self,response):
        try:return b''.join(response.streaming_content) if response.streaming else response.content
        finally:response.close()

    def legacy_files(self):
        shutil.rmtree(self.private)
        for field,data in zip(self.fields,self.contents):
            target=self.public/field.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)

    def test_uploads_are_private_and_urls_are_authenticated(self):
        for field in self.fields:
            self.assertTrue((self.private/field.name).is_file())
            self.assertFalse((self.public/field.name).exists())
            self.assertTrue(field.url.startswith('/artwork/commission-files/'))
            self.assertNotIn('/media/',field.url)

    def test_original_buyer_and_artist_can_access_all_three_types(self):
        for user in (self.buyer,self.artist):
            self.client.force_login(user)
            for field,data in zip(self.fields,self.contents):
                response=self.client.get(field.url)
                self.assertEqual(response.status_code,200)
                self.assertEqual(self.bytes(response),data)

    def test_logged_out_requests_require_login_without_exposing_bytes(self):
        self.client.logout()
        for field,data in zip(self.fields,self.contents):
            response=self.client.get(field.url)
            self.assertEqual(response.status_code,302);self.assertIn('next=',response.url)
            self.assertNotIn(data,self.bytes(response))
            self.assertIn('no-store',response['Cache-Control'])

    def test_unrelated_buyer_artist_and_staff_cannot_access_files(self):
        for user in (self.other_buyer,self.other_artist,self.staff):
            self.client.force_login(user)
            for field,data in zip(self.fields,self.contents):
                response=self.client.get(field.url)
                self.assertEqual(response.status_code,403)
                self.assertNotIn(data,self.bytes(response))

    def test_all_old_public_urls_denied_for_every_account_and_logged_out(self):
        self.legacy_files()
        for user in (None,self.other_buyer,self.other_artist,self.buyer,self.artist):
            if user:self.client.force_login(user)
            else:self.client.logout()
            for field in self.fields:
                response=self.client.get('/media/'+field.name)
                self.assertEqual(response.status_code,404)
                self.assertIn('no-store',response['Cache-Control'])

    def test_legacy_guard_blocks_normalized_and_encoded_paths(self):
        self.legacy_files()
        name=self.commission.reference_image.name
        for url in ('/media/./'+name,'/media/public/../'+name,'/media/%2e/'+name,'/media/'+name.replace('commission_refs', 'COMMISSION_REFS')):
            self.assertEqual(self.client.get(url).status_code,404)

    def test_authorized_legacy_file_is_readable_during_relocation(self):
        self.legacy_files()
        for field,data in zip(self.fields,self.contents):
            response=self.client.get(field.url)
            self.assertEqual(response.status_code,200);self.assertEqual(self.bytes(response),data)

    def test_private_responses_are_not_cached_or_shared(self):
        response=self.client.get(self.commission.reference_image.url)
        self.assertIn('no-store',response['Cache-Control'])
        self.assertIn('private',response['Cache-Control'])
        self.assertIn('Cookie',response['Vary'])
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        self.assertEqual(response['Cross-Origin-Resource-Policy'],'same-origin')
        response.close()

    def test_reference_is_inline_and_attachments_download(self):
        response=self.client.get(self.commission.reference_image.url)
        self.assertEqual(response['Content-Type'],'image/png')
        self.assertTrue(response['Content-Disposition'].startswith('inline'));response.close()
        for field in (self.message.attachment,self.delivery.delivery_file):
            response=self.client.get(field.url)
            self.assertEqual(response['Content-Type'],'application/octet-stream')
            self.assertTrue(response['Content-Disposition'].startswith('attachment'));response.close()

    def test_active_content_disguised_as_reference_is_never_rendered_inline(self):
        path=self.private/self.commission.reference_image.name;path.write_bytes(b'<script>alert("not an image")</script>')
        response=self.client.get(self.commission.reference_image.url)
        self.assertEqual(response['Content-Type'],'application/octet-stream')
        self.assertTrue(response['Content-Disposition'].startswith('attachment'));response.close()

    def test_unreferenced_file_cannot_be_downloaded(self):
        target=self.private/'commission_deliveries/orphan.txt';target.parent.mkdir(parents=True,exist_ok=True);target.write_text('private orphan')
        response=self.client.get(reverse('commission_file',kwargs={'file_name':'commission_deliveries/orphan.txt'}))
        self.assertEqual(response.status_code,403)

    def test_file_of_another_commission_is_not_authorized_by_own_commission(self):
        other=CustomRequest.objects.create(sender=self.other_buyer,receiver=self.other_artist,title='Other',requirements='Other',reference_image=ContentFile(self.image,name='other.png'))
        self.assertEqual(self.client.get(other.reference_image.url).status_code,403)

    def test_path_traversal_and_other_upload_names_rejected(self):
        for name in ('commission_refs/../secret.txt','artwork/public.png','commission_refs/../../etc/passwd','commission_refs\\reference.png'):
            response=self.client.get(reverse('commission_file',kwargs={'file_name':name}))
            self.assertEqual(response.status_code,404)

    def test_missing_authorized_file_is_404(self):
        (self.private/self.message.attachment.name).unlink()
        self.assertEqual(self.client.get(self.message.attachment.url).status_code,404)

    def test_public_artwork_images_stay_public(self):
        art=Artwork.objects.create(artist=self.artist,title='Public',price='10',image=ContentFile(self.image,name='public.png'))
        self.client.logout();response=self.client.get(art.image.url)
        self.assertEqual(response.status_code,200);self.assertEqual(self.bytes(response),self.image)

    def test_head_and_post_respect_file_permissions(self):
        response=self.client.head(self.delivery.delivery_file.url)
        self.assertEqual(response.status_code,200);response.close()
        self.client.force_login(self.other_buyer)
        self.assertEqual(self.client.head(self.delivery.delivery_file.url).status_code,403)
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.post(self.delivery.delivery_file.url).status_code,405)

    def test_storage_does_not_reuse_legacy_file_name(self):
        self.legacy_files()
        saved=PrivateCommissionStorage().save(self.message.attachment.name,ContentFile(b'new bytes'))
        self.assertNotEqual(saved,self.message.attachment.name)
        self.assertEqual((self.public/self.message.attachment.name).read_bytes(),b'private attachment')

    def test_relocation_preserves_bytes_names_and_database_references(self):
        self.legacy_files();names=[field.name for field in self.fields]
        call_command('protect_commission_files',stdout=StringIO(),stderr=StringIO())
        for name,data in zip(names,self.contents):
            self.assertFalse((self.public/name).exists());self.assertEqual((self.private/name).read_bytes(),data)
        self.commission.refresh_from_db();self.message.refresh_from_db();self.delivery.refresh_from_db()
        self.assertEqual([self.commission.reference_image.name,self.message.attachment.name,self.delivery.delivery_file.name],names)
        for field,data in zip(self.fields,self.contents):self.assertEqual(self.bytes(self.client.get(field.url)),data)

    def test_relocation_also_protects_orphaned_public_uploads(self):
        target=self.public/'commission_messages/old-orphan.txt';target.parent.mkdir(parents=True);target.write_text('old private note')
        call_command('protect_commission_files',stdout=StringIO(),stderr=StringIO())
        self.assertFalse(target.exists());self.assertEqual((self.private/'commission_messages/old-orphan.txt').read_text(),'old private note')

    def test_relocation_dry_run_and_repeated_runs(self):
        self.legacy_files()
        call_command('protect_commission_files',dry_run=True,stdout=StringIO(),stderr=StringIO())
        self.assertFalse(self.private.exists())
        call_command('protect_commission_files',stdout=StringIO(),stderr=StringIO())
        output=StringIO();call_command('protect_commission_files',stdout=output,stderr=StringIO())
        self.assertIn('Protected 0 existing file(s)',output.getvalue())

    def test_identical_private_copy_is_verified_and_public_copy_removed(self):
        self.legacy_files()
        path=self.private/self.message.attachment.name;path.parent.mkdir(parents=True);path.write_bytes(b'private attachment')
        call_command('protect_commission_files',stdout=StringIO(),stderr=StringIO())
        self.assertFalse((self.public/self.message.attachment.name).exists());self.assertEqual(path.read_bytes(),b'private attachment')

    def test_conflicting_destination_aborts_before_any_public_files_are_removed(self):
        self.legacy_files()
        path=self.private/self.commission.reference_image.name;path.parent.mkdir(parents=True);path.write_bytes(b'different bytes')
        with self.assertRaises(CommandError):call_command('protect_commission_files',stdout=StringIO(),stderr=StringIO())
        self.assertTrue(all((self.public/f.name).exists() for f in self.fields))
        self.assertEqual(path.read_bytes(),b'different bytes')

    def test_corrupt_copy_never_removes_public_original(self):
        self.legacy_files()
        with patch('artwork.management.commands.protect_commission_files.shutil.copyfileobj',side_effect=lambda src,dst,**kwargs:dst.write(b'bad copy')):
            with self.assertRaises(CommandError):call_command('protect_commission_files',stdout=StringIO(),stderr=StringIO())
        self.assertTrue(all((self.public/f.name).exists() for f in self.fields))
        self.assertFalse(any(self.private.rglob('.protect-*')))

    def test_relocation_refuses_symbolic_links(self):
        target=self.public/'commission_refs';target.mkdir(parents=True)
        (target/'linked.png').symlink_to(self.private/self.commission.reference_image.name)
        with self.assertRaises(CommandError):call_command('protect_commission_files',stdout=StringIO(),stderr=StringIO())

    def test_private_root_cannot_be_public(self):
        with override_settings(PRIVATE_MEDIA_ROOT=str(self.public/'private')):
            errors=check_private_commission_root(None)
            self.assertEqual(errors[0].id,'artwork.E001')
            with self.assertRaises(ImproperlyConfigured):PrivateCommissionStorage().save('commission_messages/unsafe.txt',ContentFile(b'not saved'))
            self.assertFalse((self.public/'private').exists())

    def test_admin_file_widget_links_use_the_protected_route(self):
        from artwork.forms import CommissionRequestForm
        html=str(CommissionRequestForm(instance=self.commission)['reference_image'])
        self.assertIn(self.commission.reference_image.url,html)
        self.assertNotIn('/media/commission_refs/',html)
