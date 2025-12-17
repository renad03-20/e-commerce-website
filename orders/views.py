from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import Order, OrderItem
from .forms import OrderCreateForm, OrderShippingForm
from cart.utils import get_or_create_cart
from artwork.models import Artwork
import stripe
from django.conf import settings
from django.urls import reverse
from django.views.generic import UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Sum, Count, Avg
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import models

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

@login_required
def artist_orders_dashboard(request):
    """
    Comprehensive artist order dashboard
    """
    # Get orders containing this artist's artworks
    orders = Order.objects.filter(
        items__artwork__artist=request.user
    ).distinct().order_by('-created')
    
    # Calculate statistics
    total_orders = orders.count()
    
    # Status breakdown
    status_counts = orders.values('status').annotate(count=models.Count('id'))
    
    # Last 30 days sales
    thirty_days_ago = datetime.now() - timedelta(days=30)
    recent_sales = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__paid=True,
        order__created__gte=thirty_days_ago
    ).aggregate(
        total_revenue=Sum('price' * models.F('quantity')),
        total_items=Sum('quantity')
    )
    
    # Monthly sales data for chart
    monthly_sales = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__paid=True,
        order__created__gte=datetime.now() - timedelta(days=365)
    ).extra({
        'month': "strftime('%%Y-%%m', orders_order.created)"
    }).values('month').annotate(
        revenue=Sum(models.F('price') * models.F('quantity')),
        orders=Count('order', distinct=True)
    ).order_by('month')
    
    # Best selling artworks
    best_sellers = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__paid=True
    ).values(
        'artwork__title', 'artwork__id'
    ).annotate(
        total_sold=Sum('quantity'),
        total_revenue=Sum(models.F('price') * models.F('quantity'))
    ).order_by('-total_sold')[:5]
    
    context = {
        'orders': orders,
        'total_orders': total_orders,
        'status_counts': status_counts,
        'recent_sales': recent_sales,
        'monthly_sales': list(monthly_sales),
        'best_sellers': best_sellers,
    }
    return render(request, 'orders/artist_orders_dashboard.html', context)

@login_required
def artist_order_detail(request, order_number):
    """
    Detailed view of an order for the artist
    """
    order = get_object_or_404(Order, order_number=order_number)
    
    # Security check - ensure artist owns items in this order
    artist_items = order.items.filter(artwork__artist=request.user)
    if not artist_items.exists():
        messages.error(request, "You don't have permission to view this order.")
        return redirect('orders:artist_orders_dashboard')
    
    if request.method == 'POST':
        # Handle status updates
        new_status = request.POST.get('status')
        tracking_number = request.POST.get('tracking_number')
        shipping_carrier = request.POST.get('shipping_carrier')
        artist_notes = request.POST.get('artist_notes')
        
        if new_status in dict(OrderItem._meta.get_field('artist_fulfillment_status').choices):
            # Update artist-specific fulfillment status for their items
            artist_items.update(artist_fulfillment_status=new_status)
            
            # Update order tracking if provided
            if tracking_number:
                order.tracking_number = tracking_number
                order.shipping_carrier = shipping_carrier
                if new_status == 'shipped' and not order.shipped_at:
                    order.shipped_at = timezone.now()
                elif new_status == 'delivered' and not order.delivered_at:
                    order.delivered_at = timezone.now()
            
            if artist_notes:
                order.artist_notes = artist_notes
            
            order.save()
            messages.success(request, f'Order status updated to {new_status}.')
        
        return redirect('orders:artist_order_detail', order_number=order.order_number)
    
    context = {
        'order': order,
        'artist_items': artist_items,
    }
    return render(request, 'orders/artist_order_detail.html', context)

@login_required
def mark_order_shipped(request, order_number):
    """
    Mark order as shipped with tracking info
    """
    order = get_object_or_404(Order, order_number=order_number)
    artist_items = order.items.filter(artwork__artist=request.user)
    
    if not artist_items.exists():
        messages.error(request, "You don't have permission to update this order.")
        return redirect('orders:artist_orders_dashboard')
    
    if request.method == 'POST':
        form = OrderShippingForm(request.POST, instance=order)
        if form.is_valid():
            order = form.save(commit=False)
            order.shipped_at = timezone.now()
            order.status = 'shipped'
            order.save()
            
            # Update artist fulfillment status
            artist_items.update(artist_fulfillment_status='shipped')
            
            messages.success(request, f'Order #{order.order_number} marked as shipped!')
            return redirect('orders:artist_order_detail', order_number=order.order_number)
    else:
        form = OrderShippingForm(instance=order)
    
    context = {
        'order': order,
        'form': form,
    }
    return render(request, 'orders/mark_shipped.html', context)

@login_required
def artist_sales_analytics(request):
    """
    Detailed sales analytics for artists
    """
    from django.db.models import Sum, Count, Avg
    from datetime import datetime, timedelta
    
    # Time periods
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    year_ago = today - timedelta(days=365)
    
    # Overall stats
    total_stats = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__paid=True
    ).aggregate(
        total_revenue=Sum(models.F('price') * models.F('quantity')),
        total_orders=Count('order', distinct=True),
        total_items=Sum('quantity'),
        avg_order_value=Avg(models.F('price') * models.F('quantity'))
    )
    
    # Time-based stats
    recent_stats = {
        'week': OrderItem.objects.filter(
            artwork__artist=request.user,
            order__paid=True,
            order__created__gte=week_ago
        ).aggregate(
            revenue=Sum(models.F('price') * models.F('quantity')),
            orders=Count('order', distinct=True)
        ),
        'month': OrderItem.objects.filter(
            artwork__artist=request.user,
            order__paid=True,
            order__created__gte=month_ago
        ).aggregate(
            revenue=Sum(models.F('price') * models.F('quantity')),
            orders=Count('order', distinct=True)
        ),
    }
    
    # Monthly revenue for chart
    monthly_revenue = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__paid=True,
        order__created__gte=year_ago
    ).extra({
        'month': "strftime('%%Y-%%m', orders_order.created)"
    }).values('month').annotate(
        revenue=Sum(models.F('price') * models.F('quantity'))
    ).order_by('month')
    
    # Top performing artworks
    top_artworks = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__paid=True
    ).values(
        'artwork__title', 'artwork__id', 'artwork__image'
    ).annotate(
        total_sold=Sum('quantity'),
        total_revenue=Sum(models.F('price') * models.F('quantity')),
        order_count=Count('order', distinct=True)
    ).order_by('-total_revenue')[:10]
    
    context = {
        'total_stats': total_stats,
        'recent_stats': recent_stats,
        'monthly_revenue': list(monthly_revenue),
        'top_artworks': top_artworks,
    }
    return render(request, 'orders/artist_sales_analytics.html', context)
