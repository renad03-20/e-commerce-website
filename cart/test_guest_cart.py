from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from io import BytesIO
from tempfile import TemporaryDirectory
from PIL import Image

from artwork.models import Artwork
from cart.models import Cart, CartItem


class GuestCartTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(MEDIA_ROOT=directory.name)
        settings.enable(); self.addCleanup(settings.disable)
        users = get_user_model()
        self.buyer = users.objects.create_user('guest-buyer', password='test-password')
        self.artist = users.objects.create_user('guest-artist')
        image = BytesIO()
        Image.new('RGB', (8, 8), 'white').save(image, format='PNG')
        self.art = Artwork.objects.create(artist=self.artist, title='Painting', price=20, stock=3,
            image=SimpleUploadedFile('painting.png', image.getvalue(), content_type='image/png'))

    def guest_add(self, quantity=1):
        self.client.post(reverse('cart:add_to_cart', args=[self.art.pk]), {'quantity': quantity})
        return Cart.objects.get(pk=self.client.session['anonymous_cart_id'])

    def test_guest_cart_survives_real_login_and_session_key_rotation(self):
        guest = self.guest_add()
        old_key = self.client.session.session_key
        self.assertTrue(self.client.login(username=self.buyer.username, password='test-password'))
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertEqual(Cart.objects.get(user=self.buyer).items.get().quantity, 1)
        self.assertFalse(Cart.objects.filter(pk=guest.pk).exists())
        self.assertNotIn('anonymous_cart_id', self.client.session)

    def test_existing_buyer_cart_is_merged_and_clamped_to_stock(self):
        cart = Cart.objects.create(user=self.buyer)
        CartItem.objects.create(cart=cart, artwork=self.art, quantity=2)
        self.guest_add(quantity=2)
        self.client.login(username=self.buyer.username, password='test-password')
        self.assertEqual(cart.items.get().quantity, 3)
        self.assertEqual(cart.items.count(), 1)
        self.art.refresh_from_db(); self.assertEqual(self.art.stock, 3)

    def test_item_that_sold_out_before_login_is_not_carried_into_checkout(self):
        self.guest_add()
        self.art.stock = 0; self.art.save()
        self.client.login(username=self.buyer.username, password='test-password')
        self.assertFalse(Cart.objects.get(user=self.buyer).items.exists())

    def test_unrelated_users_cart_cannot_be_merged(self):
        cart = Cart.objects.create(user=self.artist)
        item = CartItem.objects.create(cart=cart, artwork=self.art)
        state = self.client.session
        state['anonymous_cart_id'] = cart.pk
        state['anonymous_cart_session_key'] = 'not-a-guest-cart'
        state.save()
        self.client.login(username=self.buyer.username, password='test-password')
        self.assertTrue(CartItem.objects.filter(pk=item.pk, cart__user=self.artist).exists())
        self.assertFalse(CartItem.objects.filter(cart__user=self.buyer).exists())

    def test_wrong_guest_session_key_does_not_merge_another_sessions_items(self):
        guest = self.guest_add()
        state = self.client.session; state['anonymous_cart_session_key'] = 'wrong-session'; state.save()
        self.client.login(username=self.buyer.username, password='test-password')
        self.assertTrue(Cart.objects.filter(pk=guest.pk).exists())
        self.assertFalse(CartItem.objects.filter(cart__user=self.buyer).exists())

    def test_login_again_does_not_merge_or_duplicate_items(self):
        self.guest_add()
        self.client.login(username=self.buyer.username, password='test-password')
        self.client.login(username=self.buyer.username, password='test-password')
        self.assertEqual(Cart.objects.get(user=self.buyer).items.get().quantity, 1)

    def test_gallery_is_public_and_checkout_requires_login(self):
        self.assertEqual(self.client.get(reverse('artwork_list')).status_code, 200)
        self.guest_add()
        response = self.client.get(reverse('order_create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_cart_checkout_routes_buyer_to_shipping_details(self):
        self.guest_add()
        self.client.login(username=self.buyer.username, password='test-password')
        response = self.client.get(reverse('cart:checkout'))
        self.assertRedirects(response, reverse('order_create'))
