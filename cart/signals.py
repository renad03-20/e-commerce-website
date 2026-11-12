from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .utils import merge_guest_cart


@receiver(user_logged_in, dispatch_uid='cart.merge_guest_cart_on_login')
def merge_cart_on_login(sender, request, user, **kwargs):
    merge_guest_cart(request, user)
