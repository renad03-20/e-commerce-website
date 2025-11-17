from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import Order, OrderItem
from .forms import OrderCreateForm
from cart.utils import get_or_create_cart
from artwork.models import Artwork
import stripe
from django.conf import settings
from django.urls import reverse

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
                print(f"DEBUG: Processing cart item: {cart_item.artwork.title} x{cart_item.quantity}") 
                OrderItem.objects.create(
                    order=order,
                    artwork=cart_item.artwork,
                    price=cart_item.artwork.price,
                    quantity=cart_item.quantity
                )

                print(f'debug: order item created for {cart_item.artwork.title}')

            #!  DO NOT update stock or clear cart here!
            #! ONLY after successful payment
            # artwork = cart_item.artwork
            # print(f'debug before stock update {artwork.title}: stock: {artwork.stock}')
            # artwork.stock -= cart_item.quantity
            # artwork.save()
            # print(f'debug after stock update {artwork.title}: stock: {artwork.stock}')

            #! DO NOT clear cart here!
            #! ONLY after successful payment:
            # print(f'debug before clearing cart {cart.items.count()} items')
            # cart.items.all().delete()
            # print(f'debug after clearing cart  {cart.items.count()} items')

            #! store order ID in session for payment process
            request.session['order_id'] = order.order_number

            messages.success(request, f'Order #{order.order_number} created! Please complete payment.')
            return redirect('payment_process')
        
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
    from decimal import Decimal

    try:
        cart_total = cart.get_total_price() or Decimal('0')
        shipping_cost = Decimal('10.00')
        tax_rate = Decimal('0.08')  # 8%
        tax = cart_total * tax_rate
        grand_total = cart_total + shipping_cost + tax
    except Exception as e:
        cart_total = Decimal('0')
        shipping_cost = Decimal('0')
        tax_rate = Decimal('0.08')
        tax = Decimal('0')
        grand_total = Decimal('0')
        print(f"Calculation error: {e}")

    context = {
        'form': form,
        'cart': cart,
        'cart_items': cart_items,
        'cart_total': cart_total,
        'shipping_cost': shipping_cost,
        'tax': tax,
        'tax_rate': tax_rate * Decimal('100'),  # Convert 0.08 to 8.0 for display
        'grand_total': grand_total
    }
    return render(request, 'orders/order_create.html', context)
        
def order_created(request, order_number):
    #! Order confirmation page
    order = get_object_or_404(Order, order_number=order_number)
    
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
    print(f"DEBUG: order list called for user: {request.user} ")
    #! Display user's order history
    orders1 = Order.objects.filter(user=request.user).order_by('-created')
    orders2 = Order.objects.all().order_by('-created')
    
    print(f"DEBUG: Orders found (user filter): {orders1.count()}")  # ADD THIS
    print(f"DEBUG: All orders: {orders2.count()}")
    
    context = {
        'orders1': orders1,
        'orders2': orders2
    }
    return render(request, 'orders/order_list.html', context)

@login_required
def order_detail(request, order_number):
    #! Display order details
    order = get_object_or_404(Order, order_number=order_number)
    
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

def payment_process(request):
    """
    Handle the payment process with Stripe
    """
    # Set Stripe API key
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    order_id = request.session.get('order_id')
    order = get_object_or_404(Order, order_number=order_id)
    
    if request.method == 'POST':
        success_url = request.build_absolute_uri(reverse('payment_completed'))
        cancel_url = request.build_absolute_uri(reverse('payment_canceled'))
        
        # Stripe checkout session data
        session_data = {
            'mode': 'payment',
            'client_reference_id': order.order_number,
            'success_url': success_url,
            'cancel_url': cancel_url,
            'line_items': []
        }
        
        # Add order items to Stripe
        for item in order.items.all():
            session_data['line_items'].append({
                'price_data': {
                    'unit_amount': int(item.price * 100),  # Stripe expects cents
                    'currency': 'usd',
                    'product_data': {
                        'name': item.artwork_title,
                    },
                },
                'quantity': item.quantity,
            })
        
        # Add shipping cost as a separate line item
        session_data['line_items'].append({
            'price_data': {
                'unit_amount': 1000,  # $10.00 in cents
                'currency': 'usd',
                'product_data': {
                    'name': 'Shipping',
                },
            },
            'quantity': 1,
        })
        
        # Create Stripe checkout session
        session = stripe.checkout.Session.create(**session_data)
        
        # Redirect to Stripe checkout
        return redirect(session.url, code=303)
    
    else:
        return render(request, 'orders/payment/process.html', {'order': order})

def payment_completed(request):
    """
    Handle successful payment
    """
    order_id = request.session.get('order_id')
    if not order_id:
        messages.error(request, "no order found.")
        return redirect('home')
    
    order = get_object_or_404(Order, id=order_id)
    
    # Mark order as paid
    order.paid = True
    order.status = 'processing'
    order.save()

    # Update stock and clear cart
    try:
        from cart.utils import get_or_create_cart
        from artwork.models import Artwork
        
        # Update artwork stock
        for item in order.items.all():
            artwork = Artwork.objects.get(id=item.artwork.id)
            artwork.stock -= item.quantity
            artwork.save()
        
        # Clear the cart
        cart = get_or_create_cart(request)
        cart.items.all().delete()
        
    except Exception as e:
        print(f"DEBUG: Error in payment completion cleanup: {e}")

    # send emial notifications
    try:
        from .emails import send_artist_order_notification, send_order_confirmation

        #send confirmation to customer
        send_order_confirmation(order)

        #send notifications to artist
        for item in order.itmes.all():
            send_artist_order_notification(item)

    except Exception as e:
        print(f'email sending failed: {e}')
    
    # Clear the order ID from session
    if 'order_id' in request.session:
        del request.session['order_id']
    
    messages.success(request, f'Payment completed successfully! Order #{order.order_number} is being processed.')
    return redirect('order_created', order_number=order.order_number)  

def payment_canceled(request):
    """
    Handle cancelled payment
    """
    order_id = request.session.get('order_id')
    order = get_object_or_404(Order, id=order_id)
    
    messages.warning(request, 'Payment was cancelled. You can try again.')
    return render(request, 'orders/payment/canceled.html', {'order': order})
    