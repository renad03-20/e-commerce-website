from .models import Cart, CartItem
from artwork.models import Artwork

def get_or_create_cart(request):
    #! Get existing cart or create a new one for the current user/session
    cart = None
    
    if request.user.is_authenticated:
        # For logged-in users: get or create cart for user
        cart, created = Cart.objects.get_or_create(user=request.user)
    else:
        # For anonymous users: use session key
        session_key = request.session.session_key
        if not session_key:
            request.session.create()  # Ensure session exists
            session_key = request.session.session_key
        
        cart, created = Cart.objects.get_or_create(session_key=session_key)
    
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