from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from cart.models import CartItem, Cart
from .utils import get_or_create_cart, add_to_cart, remove_from_cart, update_cart_item, get_cart_data
from artwork.models import Artwork
from django.db import transaction

def cart_detail(request):
    #! Display the contents of the shopping cart
    cart = get_or_create_cart(request)
    
    context = {
        'cart': cart,
        'cart_items': cart.items.all()
    }

    return render(request, 'cart/cart_detail.html', context)

def add_to_cart_view(request, artwork_id):
    if request.method != 'POST':
        return redirect('artwork_list')

    try:
        quantity = int(request.POST.get('quantity', '1'))
        if quantity < 1:
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, 'Enter a whole number of at least 1.')
        return redirect('artwork_detail', pk=artwork_id)

    with transaction.atomic():
        cart = get_or_create_cart(request)
        Cart.objects.select_for_update().get(pk=cart.pk)
        artwork = get_object_or_404(Artwork, pk=artwork_id)
        existing = cart.items.filter(artwork=artwork).first()
        already_in_cart = existing.quantity if existing else 0

        if already_in_cart + quantity > artwork.stock:
            messages.error(
                request,
                f'Only {artwork.stock} available. '
                f'You already have {already_in_cart} in your cart.',
            )
        else:
            add_to_cart(request, artwork_id, quantity)
            messages.success(request, f'Added {artwork.title} to your cart!')

    return redirect('cart:cart_detail')

def remove_from_cart_view(request, item_id):
    #! remove item from cart
    if remove_from_cart(request, item_id):
        messages.success(request, "Item removed from cart.")
    else:
        messages.error(request, "Item not found in cart.")
    
    return redirect('cart:cart_detail')

def update_cart_view(request, item_id):
    if request.method != 'POST':
        return redirect('cart:cart_detail')

    try:
        quantity = int(request.POST.get('quantity', ''))
        if quantity < 1:
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, 'Enter a whole number of at least 1.')
        return redirect('cart:cart_detail')

    with transaction.atomic():
        cart = get_or_create_cart(request)
        Cart.objects.select_for_update().get(pk=cart.pk)
        item = get_object_or_404(
            CartItem.objects.select_related('artwork'),
            pk=item_id,
            cart=cart,
        )
        available = item.artwork.stock

        if quantity > available and quantity >= item.quantity:
            messages.error(
                request,
                f'Sorry, only {available} available in stock.',
            )
        else:
            item.quantity = quantity
            item.save(update_fields=['quantity'])

            if available == 0:
                messages.warning(
                    request,
                    'This artwork is out of stock. '
                    'Please remove it from your cart.',
                )
            elif quantity > available:
                messages.warning(
                    request,
                    f'Quantity reduced. Only {available} available; '
                    f'reduce the quantity to {available} or fewer '
                    f'before checkout.',
                )
            else:
                messages.success(request, 'Cart updated successfully.')

    return redirect('cart:cart_detail')

@login_required
def checkout(request):
    #! redirect to order creation
    cart = get_or_create_cart(request)
    if cart.get_total_quantity() == 0:
        messages.error(request, "Your cart is empty.")
        return redirect('cart:cart_detail')
    
    return redirect('cart:cart_detail')