from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import Order, OrderItem
from .forms import OrderCreateForm
from cart.utils import get_or_create_cart
from artwork.models import Artwork

@login_required
def order_create(request):
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
    try:
        cart_total = cart.get_total_price()
        shipping_cost = 10.00
        tax_rate = 0.08
        tax = cart_total * tax_rate
        grand_total = cart_total + shipping_cost + tax
    except Exception as e:
        # Fallback calculations if anything goes wrong
        cart_total = 0
        shipping_cost = 0
        tax = 0
        grand_total = 0
        print(f"Calculation error: {e}")

    context = {
        'form': form,
        'cart': cart,
        'cart_items': cart_items,
        'cart_total': cart_total,
        'shipping_cost': shipping_cost,
        'tax': tax,
        'tax_rate': tax_rate * 100,  #? Convert to percentage for display
        'grand_total': grand_total
    }
    return render(request, 'orders/order_create.html', context)
        
def order_created(request, order_id):
    #! Order confirmation page
    order = get_object_or_404(Order, id=order_id)
    
    #! Security check: ensure user can only see their own orders
    if request.user.is_authenticated and order.user != request.user:
        messages.error(request, "You don't have permission to view this order.")
        return redirect('home')
    
    context = {
        'order': order,
    }
    return render(request, 'orders/order_created.html', context)


@login_required
def order_list(request):
    #! Display user's order history
    orders = Order.objects.filter(user=request.user).order_by('-created')
    
    context = {
        'orders': orders,
    }
    return render(request, 'orders/order_list.html', context)

@login_required
def order_detail(request, order_id):
    #! Display order details
    order = get_object_or_404(Order, id=order_id)
    
    #! Security check: ensure user can only see their own orders
    if order.user != request.user:
        messages.error(request, "You don't have permission to view this order.")
        return redirect('order_list')
    
    context = {
        'order': order,
    }
    return render(request, 'orders/order_detail.html', context)

@login_required
def artist_orders(request):
    #! display orders for artist's artwork

   # Get orders that contain artworks by this artist
    orders = Order.objects.filter(
        items__artwork__artist=request.user
    ).distinct().order_by('-created')
    
    # Calculate artist statistics
    total_sales = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__paid=True
    ).count()
    
    total_revenue = sum(
        item.get_cost() for item in OrderItem.objects.filter(
            artwork__artist=request.user,
            order__paid=True
        )
    )
    
    context = {
        'orders': orders,
        'total_sales': total_sales,
        'total_revenue': total_revenue,
    }
    return render(request, 'orders/artist_orders.html', context)