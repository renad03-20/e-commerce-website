from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import Order, OrderItem
from .forms import OrderCreateForm
from cart.utils import get_or_create_cart
from artwork.models import Artwork

@login_required
def order_created(request):
    #! create the order form the current cart
    cart = get_or_create_cart(request)
    cart_items = cart.items.all()

    #! check if cart is empty
    if not cart_items:
        messages.error(request, 'your cart is empty')
        return redirect('cart:cart_detail')
    
    #! check for stock
    for item in cart_items:
        if item.quantity > item.artwork.stock:
            messages.error(request, f'Sorry only {item.artwork.stock} available for {item.artwork.title}')
            return redirect('cart:cart_detail')
        
    if request.method == 'POST':
        form = OrderCreateForm(request.POST)
        if form.is_valid():
            #! create order but don't save to database yet 
            order = form.save(commit=False)
            
            #! Associate order with user if logged in
            if request.user.is_authenticated:
                order.user = request.user

            #! save the order
            order.save()

            for cart_item in cart_items:
                OrderItem.objects.create(
                    order=order,
                    artwork=cart_item.artwork,
                    price=cart_item.artwork.price,
                    quantity=cart_item.quantity
                )

                #! update artwork stock
                artwork = cart_item.artwork
                artwork.stock -= cart_item.quantity
                artwork.save()

            #! clear the cart 
            cart.items.all().delete()

            messages.success(request, f'Order #{order.id} created successfully')
            return redirect('order_created', order_id=order.id)
        
    else:
        #! Pre-fill form with user data if available
        initial_data = {}
        if request.user.is_authenticated:
            initial_data = {
                'first_name': request.user.first_name,
                'last_name': request.user.last_name,
                'email': request.user.email,
            }
        form = OrderCreateForm(initial=initial_data)

    #! calculate totals for display 
    cart_total = cart.get_total_price()
    shipping_cost = 10.00  #? Fixed shipping cost for now
    tax = cart_total * 0.08  #? Example tax calculation (8%)
    grand_total = cart_total + shipping_cost + tax

    context = {
        'form': form,
        'cart': cart,
        'cart_items': cart_items,
        'cart_total': cart_total,
        'shipping_cost': shipping_cost,
        'tax':tax,
        'grand_total': grand_total
    }
    return render(request, 'orders/order_create.html', context)
        
