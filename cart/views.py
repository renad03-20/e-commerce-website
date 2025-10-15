from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from cart.models import CartItem, Cart
from .utils import get_or_create_cart, add_to_cart, remove_from_cart, update_cart_item, get_cart_data
from artwork.models import Artwork

def cart_detail(request):
    #! Display the contents of the shopping cart
    cart = get_or_create_cart(request)
    
    #! Calculate totals with proper tax
    from decimal import Decimal
    cart_total = cart.get_total_price() or Decimal('0')
    shipping_cost = Decimal('10.00')
    tax_rate = Decimal('0.08')  # 8%
    tax = cart_total * tax_rate
    grand_total = cart_total + shipping_cost + tax

    context = {
        'cart': cart,
        'cart_items': cart.items.all(),
        'cart_total': cart_total,
        'cart_total_price': cart_total,
        'cart_quantity': cart.get_total_quantity(),
        'shipping_cost': shipping_cost,
        'tax': tax,
        'tax_rate': tax_rate,
        'grand_total': grand_total
    }

    return render(request, 'cart/cart_detail.html', context)

def add_to_cart_view(request, artwork_id):
    #! Add artwork to cart and redirect to cart page
    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        
        # Check if artwork exists and has stock
        artwork = get_object_or_404(Artwork, id=artwork_id)
        
        if artwork.stock < quantity:
            messages.error(request, f"Sorry, only {artwork.stock} available in stock.")
            return redirect('artwork_detail', pk=artwork_id)
        
        try:
            add_to_cart(request, artwork_id, quantity)
            messages.success(request, f"Added {artwork.title} to your cart!")
        except Exception as e:
            messages.error(request, "Could not add item to cart.")
        
        return redirect('cart:cart_detail')
    
    return redirect('artwork_list')

def remove_from_cart_view(request, item_id):
    #! remove item from cart
    if remove_from_cart(request, item_id):
        messages.success(request, "Item removed from cart.")
    else:
        messages.error(request, "Item not found in cart.")
    
    return redirect('cart:cart_detail')

def update_cart_view(request, item_id):
    #! update item quantity in cart
    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        
        # Check stock availability 
        cart_item = get_object_or_404(CartItem, id=item_id)
        if quantity > cart_item.artwork.stock:
            messages.error(request, f"Sorry, only {cart_item.artwork.stock} available in stock.")
        elif update_cart_item(request, item_id, quantity):
            messages.success(request, "Cart updated successfully.")
        else:
            messages.error(request, "Could not update cart.")
    
    return redirect('cart:cart_detail')

@login_required
def checkout(request):
    #! redirect to order creation
    cart = get_or_create_cart(request)
    if cart.get_total_quantity() == 0:
        messages.error(request, "Your cart is empty.")
        return redirect('cart:cart_detail')
    
    return redirect('cart:cart_detail')