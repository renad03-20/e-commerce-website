from django.db.models import Sum, Count, Avg, F, ExpressionWrapper, DecimalField, Prefetch
from .forms import OrderCreateForm, OrderShippingForm, OrderStatusForm
from .permissions import artist_required
from .fulfillment import update_artist_fulfillment
from django.db import transaction
from django.views.decorators.http import require_POST
from .cancellation import PurchaseError, cancel_purchase, checkout, confirm_payment, require_fulfillable, update_refund, closed
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.urls import reverse
from django.views.generic import UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import models
from django.db.models import Sum, Count, Avg, F, ExpressionWrapper, DecimalField
from django.utils import timezone
from django.db.models.functions import TruncMonth, Coalesce
from decimal import Decimal
import stripe
import json
from datetime import datetime, timedelta

from .models import Order, OrderItem
from .forms import OrderCreateForm, OrderShippingForm
from cart.utils import get_or_create_cart
from artwork.models import Artwork

@csrf_exempt
def stripe_webhook(request):
    try:
        event = stripe.Webhook.construct_event(
            request.body, request.META.get('HTTP_STRIPE_SIGNATURE'),
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)

    try:
        if event['type'] in ('refund.updated', 'refund.failed', 'refund.created'):
            update_refund(event['data']['object'])
        elif event['type'] in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
            session = event['data']['object']
            ref = session.get('client_reference_id') or ''
            if ref.startswith('commission:'):
                from artwork.models import CustomRequest
                purchase = CustomRequest.objects.get(pk=int(ref.split(':', 1)[1]))
            else:
                purchase = Order.objects.get(order_number=ref)
            confirm_payment(type(purchase), purchase.pk, session)
    except (Order.DoesNotExist, ValueError):
        return HttpResponse(status=400)
    except Exception:
        # Log server-side; 500 makes Stripe retry transient payment/refund errors.
        import logging
        logging.getLogger(__name__).exception('Stripe event processing failed')
        return HttpResponse(status=500)
    return HttpResponse(status=200)

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


    context = {
        'form': form,
        'cart': cart,
        'cart_items': cart_items
    }
    return render(request, 'orders/order_create.html', context)
        
@login_required
def order_created(request, order_number):
    order = get_object_or_404(
        Order,
        order_number=order_number,
    )

    if order.user_id != request.user.id:
        messages.error(
            request,
            "You don't have permission to view this order.",
        )
        return redirect('order_list')

    if closed(order):
        messages.info(request, "This order is cancelled or cancellation is in progress.")
        return redirect("order_detail", order_number=order.order_number)

    if not order.paid:
        messages.info(
            request,
            'Payment has not been confirmed yet.',
        )
        return redirect(
            'order_detail',
            order_number=order.order_number,
        )

    return render(
        request,
        'orders/order_created.html',
        {'order': order},
    )


@login_required
def order_list(request):
    orders = Order.objects.filter(user=request.user).order_by('-created')
    return render(request, 'orders/order_list.html', {'orders': orders})

@login_required
def order_detail(request, order_number):
    order = get_object_or_404(
        Order,
        order_number=order_number,
    )

    if order.user_id != request.user.id:
        messages.error(
            request,
            "You don't have permission to view this order.",
        )
        return redirect('order_list')

    return render(
        request,
        'orders/order_detail.html',
        {'order': order},
    )

@login_required
@transaction.atomic
def payment_process(request):
    """
    Handle the payment process with Stripe
    """
    # Set Stripe API key
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    order_id = request.session.get('order_id')
    order = get_object_or_404(Order.objects.select_for_update(), order_number=order_id)
    if order.user_id != request.user.id:
        messages.error(request, "You don't have permission to view this order.")
        return redirect('order_list')
    if closed(order) or order.paid:
        messages.info(request, 'This order is already paid, cancelled, or being cancelled.')
        return redirect('order_detail', order_number=order.order_number)

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

        tax = order.get_tax()

        if tax > 0:
            session_data['line_items'].append({
                'price_data': {
                    'unit_amount': int(tax * 100),
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Tax (8%)',
                    },
                },
                'quantity': 1,
            })
            
        # Create Stripe checkout session
        try:
            session = checkout(order, session_data)
        except (PurchaseError, stripe.StripeError) as exc:
            messages.error(request, str(exc) if isinstance(exc, PurchaseError) else 'Could not open checkout. Please try again.')
            return redirect('order_detail', order_number=order.order_number)
        
        # Redirect to Stripe checkout
        return redirect(session.url, code=303)
    
    else:
        return render(request, 'orders/payment/process.html', {'order': order})

@login_required
def payment_completed(request):
    """
    Handle successful payment - Focus on UX and Cleanup
    """
    order_id = request.session.get('order_id')
    if not order_id:
        messages.error(request, "No order session found.")
        return redirect('home')
    
    order = get_object_or_404(Order, order_number=order_id)

    if order.user_id != request.user.id:
        messages.error(
            request,
            "You don't have permission to view this order.",
        )
        return redirect('order_list')

    if closed(order):
        messages.info(request, "This order is cancelled or cancellation is in progress.")
        return redirect("order_detail", order_number=order.order_number)

    if not order.paid:
        messages.info(request, 'Payment has not been confirmed yet.')
        return redirect(
            'order_detail',
            order_number=order.order_number,
        )
    
    try:
        from cart.utils import get_or_create_cart
        cart = get_or_create_cart(request)
        cart.items.all().delete() # Clean and simple
    except Exception as e:
        print(f"DEBUG: Cart cleanup failed: {e}")

    # Use this site's actual origin, including the local development port.
    try:
        from .emails import send_artist_order_notification, send_order_confirmation
        site_url = request.build_absolute_uri('/')
        send_order_confirmation(order, site_url=site_url)
        for item in order.items.select_related('artwork__artist').all():
            send_artist_order_notification(item, site_url=site_url)
    except Exception as e:
        print(f'Email sending failed: {e}')
    
    # Session Cleanup 
    del request.session['order_id']
    
    messages.success(request, f'Payment completed successfully! Order #{order.order_number} is being processed.')
    return redirect('order_created', order_number=order.order_number)

@login_required
def payment_canceled(request):
    order_number = request.session.get('order_id')

    if not order_number:
        messages.info(request, 'No active checkout was found.')
        return redirect('order_list')

    order = get_object_or_404(
        Order,
        order_number=order_number,
        user=request.user,
    )

    if closed(order):
        messages.info(request, 'This order is cancelled or cancellation is in progress.')
        return redirect('order_detail', order_number=order.order_number)

    if order.paid:
        messages.info(request, 'This order has already been paid.')
        return redirect('order_detail', order_number=order.order_number)

    messages.warning(
        request,
        'Payment was cancelled. You can try again.',
    )
    return render(
        request,
        'orders/payment/canceled.html',
        {'order': order},
    )

@login_required
@artist_required
def artist_orders_dashboard(request):
    orders = (
        Order.objects
        .filter(items__artwork__artist=request.user)
        .prefetch_related(Prefetch('items', queryset=OrderItem.objects.filter(artwork__artist=request.user).select_related('artwork'), to_attr='artist_items'))
        .distinct()
        .order_by('-created')
    )

    total_orders = orders.count()

    status_counts = orders.values('status').annotate(
        count=Count('id', distinct=True)
    )

    revenue_expr = ExpressionWrapper(
        F('price') * F('quantity'),
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    thirty_days_ago = timezone.localdate() - timezone.timedelta(days=30)

    recent_sales = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__paid=True,
        order__cancelled_at__isnull=True,
        order__created__gte=thirty_days_ago
    ).aggregate(
        total_revenue=Coalesce(Sum(revenue_expr), Decimal("0.00")),
        total_items=Coalesce(Sum('quantity'), 0)
    )

    monthly_sales = (
        OrderItem.objects.filter(
            artwork__artist=request.user,
            order__paid=True,
        order__cancelled_at__isnull=True,
            order__created__gte=timezone.localdate() - timezone.timedelta(days=365)
        )
        .annotate(month=TruncMonth('order__created'))
        .values('month')
        .annotate(
            revenue=Coalesce(Sum(revenue_expr), Decimal("0.00"))
        )
        .order_by('month')
    )

    best_sellers = (
        OrderItem.objects.filter(
            artwork__artist=request.user,
            order__paid=True,
        order__cancelled_at__isnull=True
        )
        .values('artwork__title', 'artwork__id')
        .annotate(
            total_sold=Coalesce(Sum('quantity'), 0),
            total_revenue=Coalesce(Sum(revenue_expr), Decimal("0.00"))
        )
        .order_by('-total_sold')[:5]
    )

    for order in orders:
        order.artist_subtotal = sum(item.get_cost() for item in order.artist_items)

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
@artist_required
@transaction.atomic
def artist_order_detail(request, order_number):
    order = get_object_or_404(Order.objects.select_for_update(), order_number=order_number)
    artist_items = order.items.filter(artwork__artist=request.user).select_related('artwork')
    if not artist_items.exists():
        messages.error(request, "You don't have permission to view this order.")
        return redirect('artist_orders_dashboard')
    fulfillment = artist_items.first()
    initial = {
        'status': fulfillment.artist_fulfillment_status,
        'tracking_number': fulfillment.tracking_number,
        'shipping_carrier': fulfillment.shipping_carrier,
        'artist_notes': fulfillment.artist_notes,
    }
    form = OrderStatusForm(request.POST if request.method == 'POST' else None, initial=initial)
    if request.method == 'POST':
        try:
            require_fulfillable(order)
            if form.is_valid():
                update_artist_fulfillment(order, request.user, form.cleaned_data)
                messages.success(request, 'Your fulfillment status has been updated.')
                return redirect('artist_order_detail', order_number=order.order_number)
            messages.error(request, 'Please correct the fulfillment details below.')
        except PurchaseError as exc:
            messages.error(request, str(exc))
            return redirect('artist_order_detail', order_number=order.order_number)
    return render(request, 'orders/artist_order_detail.html', {
        'order': order, 'artist_items': artist_items,
        'fulfillment': fulfillment, 'status_form': form,
    })

@login_required
@artist_required
@transaction.atomic
def mark_order_shipped(request, order_number):
    order = get_object_or_404(Order.objects.select_for_update(), order_number=order_number)
    artist_items = order.items.filter(artwork__artist=request.user).select_related('artwork')
    if not artist_items.exists():
        messages.error(request, "You don't have permission to update this order.")
        return redirect('artist_orders_dashboard')
    try:
        require_fulfillable(order)
    except PurchaseError as exc:
        messages.error(request, str(exc))
        return redirect('artist_order_detail', order_number=order.order_number)
    fulfillment = artist_items.first()
    form = OrderShippingForm(
        request.POST if request.method == 'POST' else None,
        initial={'tracking_number': fulfillment.tracking_number, 'shipping_carrier': fulfillment.shipping_carrier},
    )
    if request.method == 'POST' and form.is_valid():
        update_artist_fulfillment(order, request.user, dict(form.cleaned_data, status='shipped'))
        messages.success(request, f'Your artwork in order #{order.order_number} has been marked as shipped!')
        return redirect('artist_order_detail', order_number=order.order_number)
    return render(request, 'orders/mark_shipped.html', {
        'order': order, 'form': form, 'artist_items': artist_items,
    })

@login_required
@artist_required
def artist_sales_analytics(request):
    """
    Detailed sales analytics for artists
    """
    # Time periods
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    year_ago = today - timedelta(days=365)

    revenue_expr = ExpressionWrapper(
    F('price') * F('quantity'),
    output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    # Overall stats
    total_stats = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__paid=True,
        order__cancelled_at__isnull=True
    ).aggregate(
        total_revenue=Coalesce(Sum(revenue_expr), Decimal("0.00")),
        total_orders=Count('order', distinct=True),
        total_items=Coalesce(Sum('quantity'), 0),
        avg_order_value=Coalesce(Avg(revenue_expr), Decimal("0.00")),
    )
    
    # Time-based stats
    recent_stats = {
    'week': OrderItem.objects.filter(
        artwork__artist=request.user,
        order__paid=True,
        order__cancelled_at__isnull=True,
        order__created__gte=week_ago
        ).aggregate(
            revenue=Coalesce(Sum(revenue_expr), Decimal("0.00")),
            orders=Count('order', distinct=True)
        ),
        'month': OrderItem.objects.filter(
            artwork__artist=request.user,
            order__paid=True,
        order__cancelled_at__isnull=True,
            order__created__gte=month_ago
        ).aggregate(
            revenue=Coalesce(Sum(revenue_expr), Decimal("0.00")),
            orders=Count('order', distinct=True)
        ),
    }
    
    # Monthly revenue for chart
    monthly_revenue = OrderItem.objects.filter(
    artwork__artist=request.user,
    order__paid=True,
        order__cancelled_at__isnull=True,
    order__created__gte=year_ago
    ).annotate(
        month=TruncMonth('order__created')
    ).values('month').annotate(
        revenue=Coalesce(Sum(revenue_expr), Decimal("0.00"))
    ).order_by('month')

    # Top performing artworks
    top_artworks = OrderItem.objects.filter(
    artwork__artist=request.user,
    order__paid=True,
        order__cancelled_at__isnull=True
    ).values(
        'artwork__title', 'artwork__id', 'artwork__image'
    ).annotate(
        total_sold=Coalesce(Sum('quantity'), 0),
        total_revenue=Coalesce(Sum(revenue_expr), Decimal("0.00")),
        order_count=Count('order', distinct=True)
    ).order_by('-total_revenue')[:10]

    context = {
        'total_stats': total_stats,
        'recent_stats': recent_stats,
        'monthly_revenue': list(monthly_revenue),
        'top_artworks': top_artworks,
    }
    return render(request, 'orders/artist_sales_analytics.html', context)


@login_required
@require_POST
def cancel_order(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    if order.user_id != request.user.id:
        messages.error(request, "You don't have permission to cancel this order.")
        return redirect('order_list')
    try:
        cancel_purchase(Order, order.pk, request.user)
    except PurchaseError as exc:
        messages.error(request, str(exc))
    except stripe.StripeError:
        messages.error(request, 'Stripe could not finish cancellation. Your request is saved; please retry. Work is blocked.')
    else:
        messages.success(request, 'Order cancelled. Any payment refund has been submitted to Stripe.')
        if request.session.get('order_id') == order.order_number:
            request.session.pop('order_id', None)
    return redirect('order_detail', order_number=order.order_number)

