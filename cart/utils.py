from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib import messages
from .models import Cart, CartItem
from artwork.models import Artwork

def get_or_create_cart(request):
    #! Get existing cart or create a new one for the current user/session
    cart = None
    
    if request.user.is_authenticated:
        # For logged-in users: get or create cart for user
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            cart, created = Cart.objects.get_or_create(user=request.user)
    else:
        # For anonymous users: use session key
        session_key = request.session.session_key
        if not session_key:
            request.session.create()  # Ensure session exists
            session_key = request.session.session_key
        
        cart, created = Cart.objects.get_or_create(session_key=session_key)
        # Login rotates the session key. Preserve the original cart identity in
        # the server-side session so it can be merged after authentication.
        request.session['anonymous_cart_id'] = cart.pk
        request.session['anonymous_cart_session_key'] = session_key
    
    return cart

def add_to_cart(request, artwork_id, quantity=1):
    #! Add artwork to cart or update quantity if already exists
    cart = get_or_create_cart(request)
    artwork = Artwork.objects.get(id=artwork_id)
    
    # Check if artwork already in cart
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        artwork=artwork,
        defaults={'quantity': quantity}
    )
    
    if not created:
        # Update quantity if already in cart
        cart_item.quantity += quantity
        cart_item.save()
    
    return cart_item

def remove_from_cart(request, item_id):
    #! Remove item from cart
    cart = get_or_create_cart(request)
    try:
        item = CartItem.objects.get(id=item_id, cart=cart)
        item.delete()
        return True
    except CartItem.DoesNotExist:
        return False

def update_cart_item(request, item_id, quantity):
    #! Update quantity of a cart item

    cart = get_or_create_cart(request)
    try:
        item = CartItem.objects.get(id=item_id, cart=cart)
        if quantity <= 0:
            item.delete()
        else:
            item.quantity = quantity
            item.save()
        return True
    except CartItem.DoesNotExist:
        return False

def get_cart_data(request):
    #! Get cart data for templates (total price, total quantity)
    try:
        cart = get_or_create_cart(request)
        return {
            'total_price': cart.get_total_price(),
            'total_quantity': cart.get_total_quantity(),
            'items': cart.items.all()
        }
    except:
        # return empty cart data
        return{
            'total_price': 0,
            'total_quantity': 0,
            'items': []
        }

def merge_guest_cart(request, user):
    guest_id = request.session.get('anonymous_cart_id')
    old_key = request.session.get('anonymous_cart_session_key')
    if not guest_id or not old_key:
        return
    adjusted = False
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        guest = Cart.objects.select_for_update().filter(
            pk=guest_id, user__isnull=True, session_key=old_key,
        ).first()
        if guest is not None:
            cart, _ = Cart.objects.get_or_create(user=user)
            Cart.objects.select_for_update().get(pk=cart.pk)
            for item in guest.items.select_related('artwork').order_by('pk'):
                existing = cart.items.filter(artwork_id=item.artwork_id).first()
                desired = item.quantity + (existing.quantity if existing else 0)
                quantity = min(desired, item.artwork.stock)
                adjusted |= quantity != desired
                if existing:
                    if quantity > 0:
                        existing.quantity = quantity
                        existing.save(update_fields=['quantity'])
                    else:
                        existing.delete()
                elif quantity > 0:
                    CartItem.objects.create(cart=cart, artwork=item.artwork, quantity=quantity)
            guest.delete()
    request.session.pop('anonymous_cart_id', None)
    request.session.pop('anonymous_cart_session_key', None)
    if adjusted:
        messages.info(request, 'Some cart quantities were adjusted to current artwork availability.', fail_silently=True)
