from django.core.paginator import Paginator
from django.db.models import Prefetch
from accounts.models import UserProfile
from .permissions import artist_accounts, is_artist_account
from django.db import transaction
from django.views.decorators.http import require_POST
from orders.cancellation import PurchaseError, cancel_purchase, checkout, closed, require_fulfillable
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.urls import reverse
from .models import (
    Artwork,
    Category,
    Tag,
    CustomRequest,
    CommissionMessage,
    CommissionDelivery,
    CommissionRevisionRequest,
    CommissionStatusHistory,
)
from .forms import (
    ArtworkForm,
    CommissionRequestForm,
    CommissionAcceptForm,
    CommissionDeclineForm,
    CommissionMessageForm,
    CommissionDeliveryForm,
    CommissionRevisionRequestForm,
    CommissionCancelForm,
)
from orders.models import OrderItem
from django.db.models import Sum, Count
from django.utils import timezone
import stripe
from django.conf import settings

def is_artist(user):
    return is_artist_account(user)

@login_required
def artwork_list(request):
    artworks = Artwork.objects.filter(stock__gt=0)
    categories = Category.objects.all()
    
    # Filter by category if provided
    category_slug = request.GET.get('category')
    if category_slug:
        artworks = artworks.filter(category__slug=category_slug)
    
    context = {
        'artworks': artworks,
        'categories': categories,
    }
    return render(request, 'products/artwork_list.html', context)

def artwork_detail(request, pk):
    artwork = get_object_or_404(Artwork, pk=pk)
    
    if artwork.category:
        interests = request.session.get('interests', {})
        category_id = str(artwork.category.id)
        # Increment the "score" for this category
        interests[category_id] = interests.get(category_id, 0) + 1
        request.session['interests'] = interests
    
    context = {
        'artwork': artwork,
        'related_artworks': Artwork.objects.filter(category=artwork.category).exclude(pk=pk)[:4],
        'artist_accepting_commissions': is_artist(artwork.artist) and bool(getattr(getattr(artwork.artist, 'userprofile', None), 'is_available_for_commissions', False))
    }
    return render(request, 'products/artwork_detail.html', context)

@login_required
@user_passes_test(is_artist)
def artwork_create(request):
    if request.method == 'POST':
        form = ArtworkForm(request.POST, request.FILES)
        if form.is_valid():
            artwork = form.save(commit=False)
            artwork.artist = request.user
            artwork.save()
            form.save_m2m()  # Save many-to-many data
            messages.success(request, 'Artwork created successfully!')
            return redirect('artwork_detail', pk=artwork.pk)
    else:
        form = ArtworkForm()
    
    context = {
        'form': form,
        'title': 'Add New Artwork'
    }
    return render(request, 'products/artwork_form.html', context)

@login_required
@user_passes_test(is_artist)
def artwork_update(request, pk):
    artwork = get_object_or_404(Artwork, pk=pk)
    
    # Check if the user is the artist who created this artwork
    if artwork.artist != request.user and not request.user.is_superuser:
        messages.error(request, 'You can only edit your own artwork.')
        return redirect('artwork_list')
    
    if request.method == 'POST':
        form = ArtworkForm(request.POST, request.FILES, instance=artwork)
        if form.is_valid():
            form.save()
            messages.success(request, 'Artwork updated successfully!')
            return redirect('artwork_detail', pk=artwork.pk)
    else:
        form = ArtworkForm(instance=artwork)
    
    context = {
        'form': form,
        'title': 'Edit Artwork',
        'artwork': artwork
    }
    return render(request, 'products/artwork_form.html', context)

@login_required
@user_passes_test(is_artist)
def artwork_delete(request, pk):
    artwork = get_object_or_404(Artwork, pk=pk)
    
    # Check if the user is the artist who created this artwork
    if artwork.artist != request.user and not request.user.is_superuser:
        messages.error(request, 'You can only delete your own artwork.')
        return redirect('artwork_list')
    
    if request.method == 'POST':
        try:
            #! First, remove any cart items that reference this artwork
            try:
                from cart.models import CartItem
                CartItem.objects.filter(artwork=artwork).delete()
            except Exception as e:
                #! If cart items can't be deleted due to migration issues, continue anyway
                print(f"Warning: Could not delete cart items: {e}")
            
            #! Delete the artwork
            artwork.delete()
            messages.success(request, 'Artwork deleted successfully!')
            return redirect('artwork_list')
            
        except Exception as e:
            messages.error(request, f'Error deleting artwork: {str(e)}')
            return redirect('artwork_detail', pk=artwork.pk)
    
    context = {
        'artwork': artwork
    }
    return render(request, 'products/artwork_delete.html', context)

@login_required
@user_passes_test(is_artist)
def artist_dashboard(request):
    #! Get artist's artworks
    artworks = Artwork.objects.filter(artist=request.user).order_by('-created_at')

    artist_order_items = OrderItem.objects.filter(artwork__artist=request.user)
    
    #! Calculate statistics
    total_artworks = artworks.count()
    
    #! Calculate real sales data
    total_sales = artist_order_items.aggregate(total_sold=Sum('quantity'))['total_sold'] or 0
    total_revenue = sum(item.get_cost() for item in artist_order_items)

    #! Get paid orders only for revenue calculation
    paid_order_items = artist_order_items.filter(order__paid=True).exclude(order__status='cancelled')
    actual_revenue = sum(item.get_cost() for item in paid_order_items)
    
    #! Best selling artwork
    best_selling = artist_order_items.values('artwork__title').annotate(
        total_sold=Sum('quantity')
    ).order_by('-total_sold').first()

    best_selling_artwork = None
    if best_selling:
        best_selling_artwork = Artwork.objects.filter(
            title=best_selling['artwork__title'],
            artist=request.user
        ).first()
    

    
    #! Calculate revenue from artworks (placeholder - will be replaced with actual order data)
    revenue_from_artworks = artworks.aggregate(total=Sum('price'))['total'] or 0
    
    #! Get recent artworks (last 5)
    recent_artworks = artworks[:5]
    
    #! orders this month
    this_month = timezone.now().month
    orders_this_month = OrderItem.objects.filter(
        artwork__artist=request.user,
        order__created__month=this_month
    ).count()
    
    context = {
        'artworks': artworks,
        'recent_artworks': recent_artworks,
        'total_artworks': artworks.count(),
        'total_sales': total_sales,
        'total_revenue': actual_revenue,
        'revenue_from_artworks': total_revenue,
        'best_selling_artwork': best_selling_artwork,
        'orders_this_month': orders_this_month,
        'artist_order_items': artist_order_items,
    }
    return render(request, 'products/artist_dashboard.html', context)

def user_view_of_artist(request, artist_id):
    artist = get_object_or_404(User, pk=artist_id)
    if not is_artist(artist):
        messages.error(request, 'This account is not an active artist.')
        return redirect('artist_list')
    # Keep existing profile POST links working; authentication and all recipient
    # checks live in the dedicated request view.
    if request.method == 'POST':
        return commission_request(request, artist_id)
    artist_profile = getattr(artist, 'userprofile', None)
    artworks = Artwork.objects.filter(artist=artist).order_by('-created_at')
    best_seller = (
        OrderItem.objects.filter(artwork__artist=artist, order__paid=True)
        .exclude(order__status='cancelled')
        .values('artwork_id').annotate(total_sold=Sum('quantity'))
        .order_by('-total_sold', 'artwork_id').first()
    )
    best_selling_artwork = artworks.filter(pk=best_seller['artwork_id']).first() if best_seller else None
    return render(request, 'products/user_view_of_artist.html', {
        'artist': artist, 'artist_profile': artist_profile,
        'artworks': artworks, 'best_selling_artwork': best_selling_artwork,
        'accepting_commissions': bool(artist_profile and artist_profile.is_available_for_commissions),
    })


def _commission_participant_guard(request, commission):
    if not commission.is_participant(request.user):
        messages.error(request, "You don't have permission to access this commission.")
        return False
    return True


def _log_commission_status(commission, to_status, user=None, note=''):
    CommissionStatusHistory.objects.create(
        commission=commission,
        from_status=commission.status or '',
        to_status=to_status,
        changed_by=user,
        note=note,
    )
    commission.status = to_status


def _notify_commission(commission, subject, message, to_user):
    try:
        from .emails import send_commission_email

        send_commission_email(subject, message, getattr(to_user, 'email', None))
    except Exception as exc:
        print(f"Commission email error: {exc}")


@login_required
def commission_list(request):
    sent_commissions = (
        CustomRequest.objects.filter(sender=request.user)
        .select_related('receiver')
        .order_by('-created_at')
    )
    received_commissions = (
        CustomRequest.objects.filter(receiver=request.user)
        .select_related('sender')
        .order_by('-created_at')
    )

    context = {
        'sent_commissions': sent_commissions,
        'received_commissions': received_commissions if is_artist(request.user) else CustomRequest.objects.none(),
        'is_artist': is_artist(request.user),
    }
    return render(request, 'commissions/commission_list.html', context)


@login_required
def commission_detail(request, commission_id):
    commission = get_object_or_404(CustomRequest, id=commission_id)
    if not _commission_participant_guard(request, commission):
        return redirect('commission_list')

    context = {
        'commission': commission,
        'is_artist': is_artist(request.user),
        'is_commission_artist': is_artist(request.user) and request.user.pk == commission.receiver_id,
        'is_buyer': request.user == commission.sender,
        'accept_form': CommissionAcceptForm(
            initial={'price': commission.price, 'artist_deadline': commission.artist_deadline}
        ),
        'decline_form': CommissionDeclineForm(
            initial={'reason_for_declined': commission.reason_for_declined}
        ),
        'message_form': CommissionMessageForm(),
        'delivery_form': CommissionDeliveryForm(),
        'revision_form': CommissionRevisionRequestForm(),
        'cancel_form': CommissionCancelForm(),
        'deliveries': commission.deliveries.all(),
        'thread_messages': commission.messages.select_related('sender').all(),
        'revisions': commission.revisions.select_related('requested_by').all(),
        'status_history': commission.status_history.select_related('changed_by').all(),
        'status_requested': CustomRequest.STATUS_REQUESTED,
        'status_awaiting_payment': CustomRequest.STATUS_AWAITING_PAYMENT,
        'status_awaiting_artist': CustomRequest.STATUS_AWAITING_ARTIST,
        'status_in_progress': CustomRequest.STATUS_IN_PROGRESS,
        'status_delivered': CustomRequest.STATUS_DELIVERED,
        'status_revision_requested': CustomRequest.STATUS_REVISION_REQUESTED,
        'status_completed': CustomRequest.STATUS_COMPLETED,
        'status_declined': CustomRequest.STATUS_DECLINED,
        'status_canceled': CustomRequest.STATUS_CANCELED,
    }
    return render(request, 'commissions/commission_detail.html', context)


@login_required
def commission_message_create(request, commission_id):
    commission = get_object_or_404(CustomRequest, id=commission_id)
    if not _commission_participant_guard(request, commission):
        return redirect('commission_list')

    if request.method == 'POST':
        form = CommissionMessageForm(request.POST, request.FILES)
        if form.is_valid():
            message = form.save(commit=False)
            message.commission = commission
            message.sender = request.user
            message.save()
            messages.success(request, 'Message sent.')
        else:
            messages.error(request, 'Could not send message. Please check the form.')
    return redirect('commission_detail', commission_id=commission_id)


@login_required
@require_POST
@transaction.atomic
def commission_accept(request, commission_id):
    commission = get_object_or_404(CustomRequest.objects.select_for_update(), id=commission_id)
    if closed(commission):
        messages.error(request, 'This commission is cancelled or cancellation is in progress.')
        return redirect('commission_detail', commission_id=commission_id)

    if not is_artist(request.user) or request.user.pk != commission.receiver_id:
        messages.error(request, "Only the artist can accept this commission.")
        return redirect('commission_detail', commission_id=commission_id)

    if commission.status != CustomRequest.STATUS_REQUESTED:
        messages.error(request, "This commission can no longer be accepted.")
        return redirect('commission_detail', commission_id=commission_id)

    if request.method == 'POST':
        form = CommissionAcceptForm(request.POST)
        if form.is_valid():
            commission.price = form.cleaned_data['price']
            commission.artist_deadline = form.cleaned_data.get('artist_deadline')
            commission.accepted_at = timezone.now()
            _log_commission_status(
                commission,
                CustomRequest.STATUS_AWAITING_PAYMENT,
                request.user,
                note='Commission accepted. Awaiting payment.',
            )
            commission.save()

            note = form.cleaned_data.get('note')
            if note:
                CommissionMessage.objects.create(
                    commission=commission,
                    sender=request.user,
                    body=note,
                )

            _notify_commission(
                commission,
                subject=f"Commission accepted by {request.user.username}",
                message=f"Your commission '{commission.title}' was accepted. Please complete payment to begin.",
                to_user=commission.sender,
            )

            messages.success(request, 'Commission accepted. The buyer has been notified to pay.')
        else:
            messages.error(request, 'Please provide a valid price to accept.')
    return redirect('commission_detail', commission_id=commission_id)


@login_required
@require_POST
@transaction.atomic
def commission_decline(request, commission_id):
    commission = get_object_or_404(CustomRequest.objects.select_for_update(), id=commission_id)
    if closed(commission):
        messages.error(request, 'This commission is cancelled or cancellation is in progress.')
        return redirect('commission_detail', commission_id=commission_id)

    if not is_artist(request.user) or request.user.pk != commission.receiver_id:
        messages.error(request, "Only the artist can decline this commission.")
        return redirect('commission_detail', commission_id=commission_id)

    if commission.status != CustomRequest.STATUS_REQUESTED:
        messages.error(request, "This commission can no longer be declined.")
        return redirect('commission_detail', commission_id=commission_id)

    if request.method == 'POST':
        form = CommissionDeclineForm(request.POST)
        if form.is_valid():
            commission.reason_for_declined = form.cleaned_data['reason_for_declined']
            _log_commission_status(
                commission,
                CustomRequest.STATUS_DECLINED,
                request.user,
                note='Commission declined.',
            )
            commission.save()
            _notify_commission(
                commission,
                subject=f"Commission declined by {request.user.username}",
                message=f"Your commission '{commission.title}' was declined. Reason: {commission.reason_for_declined}",
                to_user=commission.sender,
            )
            messages.info(request, 'Commission declined.')
        else:
            messages.error(request, 'Please provide a reason to decline.')
    return redirect('commission_detail', commission_id=commission_id)


@login_required
@require_POST
def commission_cancel(request, commission_id):
    commission = get_object_or_404(CustomRequest, pk=commission_id)
    if not _commission_participant_guard(request, commission):
        return redirect('commission_list')
    form = CommissionCancelForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Please provide a valid cancellation note.')
        return redirect('commission_detail', commission_id=commission.pk)
    try:
        cancel_purchase(CustomRequest, commission.pk, request.user, form.cleaned_data.get('cancel_reason', ''))
    except PurchaseError as exc:
        messages.error(request, str(exc))
    except stripe.StripeError:
        messages.error(request, 'Stripe could not finish cancellation. Your request is saved; please retry. Work is blocked.')
    else:
        messages.success(request, 'Commission cancelled. Any payment refund has been submitted to Stripe.')
    return redirect('commission_detail', commission_id=commission.pk)


@login_required
@transaction.atomic
def commission_payment_start(request, commission_id):
    commission = get_object_or_404(CustomRequest.objects.select_for_update(), id=commission_id)
    if request.user != commission.sender:
        messages.error(request, "Only the buyer can pay for this commission.")
        return redirect('commission_detail', commission_id=commission_id)

    if closed(commission) or commission.status != CustomRequest.STATUS_AWAITING_PAYMENT:
        messages.error(request, "This commission isn't ready for payment.")
        return redirect('commission_detail', commission_id=commission_id)

    if not commission.price:
        messages.error(request, "The artist hasn't set a price yet.")
        return redirect('commission_detail', commission_id=commission_id)

    stripe.api_key = settings.STRIPE_SECRET_KEY

    if request.method == 'POST':
        success_url = request.build_absolute_uri(
            reverse('commission_payment_completed', args=[commission.id])
        )
        cancel_url = request.build_absolute_uri(
            reverse('commission_payment_canceled', args=[commission.id])
        )

        session_data = dict(
            mode='payment',
            client_reference_id=f'commission:{commission.id}',
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=[
                {
                    'price_data': {
                        'unit_amount': int(commission.price * 100),
                        'currency': 'usd',
                        'product_data': {
                            'name': f'Custom commission: {commission.title}',
                        },
                    },
                    'quantity': 1,
                }
            ],
            metadata={'commission_id': str(commission.id), 'type': 'commission'},
        )
        try:
            session = checkout(commission, session_data)
        except (PurchaseError, stripe.StripeError) as exc:
            messages.error(request, str(exc) if isinstance(exc, PurchaseError) else 'Could not open checkout. Please try again.')
            return redirect('commission_detail', commission_id=commission.id)
        return redirect(session.url, code=303)

    return render(request, 'commissions/payment_process.html', {'commission': commission})


@login_required
def commission_payment_completed(request, commission_id):
    commission = get_object_or_404(CustomRequest, pk=commission_id)
    if request.user.id != commission.sender_id:
        messages.error(request, "You don't have permission to view this payment.")
        return redirect('commission_list')
    if closed(commission):
        messages.info(request, 'This commission is cancelled or cancellation is in progress.')
    elif not commission.paid_at:
        messages.info(request, 'Payment has not been confirmed yet. Please check again shortly.')
    else:
        messages.success(request, 'Payment confirmed. Your commission is waiting for the artist to start work.')
    return redirect('commission_detail', commission_id=commission.pk)


@login_required
def commission_payment_canceled(request, commission_id):
    commission = get_object_or_404(CustomRequest, id=commission_id)
    if request.user != commission.sender:
        messages.error(request, "You don't have permission to view this payment.")
        return redirect('commission_list')
    return render(request, 'commissions/payment_canceled.html', {'commission': commission})


@login_required
@require_POST
@transaction.atomic
def commission_delivery_create(request, commission_id):
    commission = get_object_or_404(CustomRequest.objects.select_for_update(), id=commission_id)
    if closed(commission):
        messages.error(request, 'This commission is cancelled or cancellation is in progress.')
        return redirect('commission_detail', commission_id=commission_id)

    if not is_artist(request.user) or request.user.pk != commission.receiver_id:
        messages.error(request, "Only the artist can deliver this commission.")
        return redirect('commission_detail', commission_id=commission_id)

    if commission.status not in [
        CustomRequest.STATUS_IN_PROGRESS,
        CustomRequest.STATUS_REVISION_REQUESTED,
    ]:
        messages.error(request, "This commission isn't ready for delivery.")
        return redirect('commission_detail', commission_id=commission_id)

    if request.method == 'POST':
        form = CommissionDeliveryForm(request.POST, request.FILES)
        if form.is_valid():
            delivery = form.save(commit=False)
            delivery.commission = commission
            delivery.delivered_by = request.user
            delivery.save()

            if commission.status == CustomRequest.STATUS_REVISION_REQUESTED:
                latest_revision = commission.revisions.first()
                if latest_revision and not latest_revision.resolved_at:
                    latest_revision.resolved_at = timezone.now()
                    latest_revision.save(update_fields=['resolved_at'])

            commission.delivered_at = timezone.now()
            _log_commission_status(
                commission,
                CustomRequest.STATUS_DELIVERED,
                request.user,
                note='Delivery submitted.',
            )
            commission.save()
            _notify_commission(
                commission,
                subject="Commission delivery sent",
                message=f"A delivery was sent for '{commission.title}'.",
                to_user=commission.sender,
            )
            messages.success(request, 'Delivery sent to the buyer.')
        else:
            messages.error(request, 'Please include a file or link for delivery.')
    return redirect('commission_detail', commission_id=commission_id)


@login_required
def commission_request_revision(request, commission_id):
    commission = get_object_or_404(CustomRequest, id=commission_id)
    if request.user != commission.sender:
        messages.error(request, "Only the buyer can request revisions.")
        return redirect('commission_detail', commission_id=commission_id)

    if commission.status != CustomRequest.STATUS_DELIVERED:
        messages.error(request, "Revisions can only be requested after delivery.")
        return redirect('commission_detail', commission_id=commission_id)

    if not commission.can_request_revision():
        messages.error(request, "You've reached the revision limit.")
        return redirect('commission_detail', commission_id=commission_id)

    if request.method == 'POST':
        form = CommissionRevisionRequestForm(request.POST)
        if form.is_valid():
            revision = form.save(commit=False)
            revision.commission = commission
            revision.requested_by = request.user
            revision.save()
            commission.revision_count += 1
            _log_commission_status(
                commission,
                CustomRequest.STATUS_REVISION_REQUESTED,
                request.user,
                note='Revision requested.',
            )
            commission.save()
            _notify_commission(
                commission,
                subject="Revision requested",
                message=f"The buyer requested a revision for '{commission.title}'.",
                to_user=commission.receiver,
            )
            messages.success(request, 'Revision request sent to the artist.')
        else:
            messages.error(request, 'Please describe the revision you need.')
    return redirect('commission_detail', commission_id=commission_id)


@login_required
def commission_mark_complete(request, commission_id):
    commission = get_object_or_404(CustomRequest, id=commission_id)
    if request.user != commission.sender:
        messages.error(request, "Only the buyer can mark this as complete.")
        return redirect('commission_detail', commission_id=commission_id)

    if commission.status != CustomRequest.STATUS_DELIVERED:
        messages.error(request, "You can only complete a delivered commission.")
        return redirect('commission_detail', commission_id=commission_id)

    commission.completed_at = timezone.now()
    _log_commission_status(
        commission,
        CustomRequest.STATUS_COMPLETED,
        request.user,
        note='Commission completed.',
    )
    commission.save()
    _notify_commission(
        commission,
        subject="Commission completed",
        message=f"The commission '{commission.title}' was marked complete by the buyer.",
        to_user=commission.receiver,
    )
    messages.success(request, 'Commission marked as complete. Thank you!')
    return redirect('commission_detail', commission_id=commission_id)


@login_required
@require_POST
@transaction.atomic
def commission_start_work(request, commission_id):
    commission = get_object_or_404(CustomRequest.objects.select_for_update(), pk=commission_id)
    if not is_artist(request.user) or request.user.pk != commission.receiver_id:
        messages.error(request, "Only the artist can start this commission.")
        return redirect('commission_list')
    try:
        require_fulfillable(commission)
        if commission.status != CustomRequest.STATUS_AWAITING_ARTIST:
            raise PurchaseError('This commission is not waiting to start.')
    except PurchaseError as exc:
        messages.error(request, str(exc))
    else:
        commission.work_started_at = timezone.now()
        _log_commission_status(commission, CustomRequest.STATUS_IN_PROGRESS, request.user, note='Artist started work; buyer cancellation closed.')
        commission.save()
        messages.success(request, 'Work started. Buyer cancellation is now closed.')
    return redirect('commission_detail', commission_id=commission.pk)



def artist_list(request):
    artists = artist_accounts().annotate(artwork_count=Count('artworks', distinct=True))
    query = request.GET.get('q', '').strip()[:100]
    open_only = request.GET.get('open') == '1'
    if query:
        artists = artists.filter(username__icontains=query)
    if open_only:
        artists = artists.filter(userprofile__is_available_for_commissions=True)
    artists = artists.order_by('username', 'pk').prefetch_related(
        Prefetch('artworks', queryset=Artwork.objects.order_by('-created_at', '-pk')[:3], to_attr='portfolio_preview')
    )
    page = Paginator(artists, 12).get_page(request.GET.get('page'))
    return render(request, 'products/artist_list.html', {
        'page_obj': page, 'query': query, 'open_only': open_only,
    })


@login_required
@transaction.atomic
def commission_request(request, artist_id):
    artist = get_object_or_404(User, pk=artist_id)
    if not is_artist(artist):
        messages.error(request, 'Commissions can only be sent to an active artist.')
        return redirect('artist_list')
    if request.user.pk == artist.pk:
        messages.error(request, "You can't request a commission from yourself.")
        return redirect('user_view_of_artist', artist_id=artist.pk)
    artist_profile = UserProfile.objects.select_for_update().filter(user=artist).first()
    accepting = bool(artist_profile and artist_profile.is_available_for_commissions)
    form = CommissionRequestForm(request.POST if request.method == 'POST' else None, request.FILES if request.method == 'POST' else None)
    if request.method == 'POST':
        if not accepting:
            form.is_valid()
            form.add_error(None, 'This artist is not accepting commissions right now. Your request has not been sent.')
        elif form.is_valid():
            commission = form.save(commit=False)
            commission.sender = request.user
            commission.receiver = artist
            commission.status = CustomRequest.STATUS_REQUESTED
            commission.save()
            CommissionStatusHistory.objects.create(
                commission=commission, from_status='', to_status=commission.status,
                changed_by=request.user, note='Commission request submitted.',
            )
            _notify_commission(
                commission, subject=f'New commission request from {request.user.username}',
                message=f'You received a new commission request: {commission.title}.', to_user=artist,
            )
            messages.success(request, f'Your request has been sent to {artist.username}!')
            return redirect('commission_detail', commission_id=commission.pk)
    return render(request, 'commissions/commission_request.html', {
        'artist': artist, 'artist_profile': artist_profile,
        'accepting_commissions': accepting, 'form': form,
    })

