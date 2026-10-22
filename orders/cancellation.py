"""Cancellation/payment transitions shared by artwork orders and commissions.

All fulfillment writers must lock the same parent row before checking this state.
Stripe operations use stable keys; failures leave cancellation requested so work
cannot start while a buyer retries. No exception is turned into payment success.
"""
from datetime import datetime, time, timezone as datetime_timezone

import stripe
from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from artwork.models import Artwork, CustomRequest, CommissionStatusHistory
from .models import Order


class PurchaseError(Exception):
    pass


def is_commission(purchase):
    return isinstance(purchase, CustomRequest)


def reference(purchase):
    return f'commission:{purchase.pk}' if is_commission(purchase) else purchase.order_number


def is_paid(purchase):
    return bool(purchase.paid_at) if is_commission(purchase) else purchase.paid


def closed(purchase):
    if is_commission(purchase):
        return bool(purchase.cancellation_requested_at or purchase.canceled_at or purchase.status in ('canceled', 'declined'))
    return bool(purchase.cancellation_requested_at or purchase.cancelled_at or purchase.status == 'cancelled')


def can_buyer_cancel(purchase):
    if is_commission(purchase):
        return (
            not purchase.work_started_at
            and purchase.status in ('requested', 'awaiting_payment', 'awaiting_artist')
        )
    return (
        not purchase.preparation_started_at
        and purchase.status in ('pending', 'processing')
        and not purchase.shipped_at
        and not purchase.delivered_at
        and not purchase.items.exclude(artist_fulfillment_status__in=['', 'pending']).exists()
    )


def require_fulfillable(purchase):
    if closed(purchase):
        raise PurchaseError('This order is cancelled or cancellation is in progress.')
    paid = purchase.paid_at if is_commission(purchase) else purchase.paid
    if not paid:
        raise PurchaseError('Payment has not been confirmed. You cannot update fulfillment yet.')


def _stripe(call, *args, **kwargs):
    return call(*args, api_key=settings.STRIPE_SECRET_KEY, **kwargs)


def _session_list(purchase):
    """Include older checkouts created before the session ID was stored locally."""
    created = purchase.created_at if is_commission(purchase) else datetime.combine(
        purchase.created, time.min, tzinfo=datetime_timezone.utc,
    )
    sessions = _stripe(
        stripe.checkout.Session.list,
        created={'gte': int(created.timestamp())}, limit=100,
    )
    return [s for s in sessions.auto_paging_iter() if s.get('client_reference_id') == reference(purchase)]


def checkout(purchase, session_data):
    """Called with a locked purchase; one reusable open Checkout Session."""
    if closed(purchase):
        raise PurchaseError('This order is cancelled or cancellation is in progress.')
    if is_paid(purchase):
        raise PurchaseError('This order has already been paid.')
    previous_id = purchase.stripe_checkout_session_id
    if previous_id:
        previous = _stripe(stripe.checkout.Session.retrieve, previous_id)
        if previous.get('status') == 'open':
            return previous
        if previous.get('status') == 'complete':
            raise PurchaseError('Payment is being confirmed. Please check your order shortly.')
    # The prior session ID is persisted. A lost response/rolled-back DB write
    # therefore uses the same key again instead of creating another checkout.
    session = _stripe(
        stripe.checkout.Session.create, **session_data,
        idempotency_key=f'checkout:{reference(purchase)}:{previous_id or "initial"}',
    )
    purchase.stripe_checkout_session_id = session.id
    purchase.save(update_fields=['stripe_checkout_session_id'])
    return session


def _refund(purchase, payment_intent):
    ledger = dict(purchase.cancellation_refunds)
    recorded = ledger.get(payment_intent)
    if recorded:
        refund = _stripe(stripe.Refund.retrieve, recorded['id'])
    else:
        # Recover an earlier successful API call even after Stripe's 24h
        # idempotency retention or a DB/process failure after the API response.
        refunds = _stripe(stripe.Refund.list, payment_intent=payment_intent, limit=100)
        refund = next((r for r in refunds.auto_paging_iter()
                       if r.get('metadata', {}).get('cancellation_reference') == reference(purchase)), None)
        if refund is None:
            refund = _stripe(
                stripe.Refund.create,
                payment_intent=payment_intent,
                reason='requested_by_customer',
                metadata={'cancellation_reference': reference(purchase)},
                idempotency_key=f'cancel:{reference(purchase)}:{payment_intent}',
            )
    ledger[payment_intent] = {'id': refund.id, 'status': refund.status}
    purchase.cancellation_refunds = ledger
    purchase.save(update_fields=['cancellation_refunds'])
    if refund.status in ('failed', 'canceled'):
        raise PurchaseError('The refund needs support. Your cancellation request is saved and work is blocked.')
    return refund


def cancel_purchase(model, pk, user, cancel_reason=''):
    """Freeze first, then expire checkouts/refund. Retrying never restocks twice."""
    with transaction.atomic():
        purchase = model.objects.select_for_update().get(pk=pk)
        buyer_id = purchase.sender_id if is_commission(purchase) else purchase.user_id
        artist_cancellation = is_commission(purchase) and user.pk == purchase.receiver_id
        if user.pk != buyer_id and not artist_cancellation:
            raise PurchaseError("You don't have permission to cancel this order.")
        if not purchase.cancellation_requested_at:
            if artist_cancellation:
                allowed = purchase.status not in ('completed', 'declined', 'canceled')
            else:
                allowed = can_buyer_cancel(purchase)
            if not allowed:
                raise PurchaseError('This order cannot be cancelled because work has started or the order is closed.')
            purchase.cancellation_requested_at = timezone.now()
            fields = ['cancellation_requested_at']
            if is_commission(purchase):
                purchase.cancel_reason = cancel_reason
                fields.append('cancel_reason')
            purchase.save(update_fields=fields)

    with transaction.atomic():
        purchase = model.objects.select_for_update().get(pk=pk)
        done = purchase.canceled_at if is_commission(purchase) else purchase.cancelled_at
        sessions = _session_list(purchase)
        # Also retrieve the tracked session in case list pagination races with creation.
        tracked = purchase.stripe_checkout_session_id
        if tracked and not any(s.id == tracked for s in sessions):
            sessions.append(_stripe(stripe.checkout.Session.retrieve, tracked))
        payment_intents = set()
        if purchase.stripe_payment_intent_id:
            payment_intents.add(purchase.stripe_payment_intent_id)
        for session in sessions:
            if session.get('status') == 'open':
                try:
                    session = _stripe(stripe.checkout.Session.expire, session.id)
                except stripe.InvalidRequestError:
                    # Payment may have won the race with session expiry.
                    session = _stripe(stripe.checkout.Session.retrieve, session.id)
                    if session.get('status') == 'open':
                        raise
            if session.get('payment_status') == 'paid':
                intent = session.get('payment_intent')
                if not intent:
                    raise PurchaseError('Payment information is still being confirmed. Retry cancellation shortly.')
                payment_intents.add(intent)
            elif session.get('status') == 'complete':
                # Delayed payment methods must resolve before cancellation settles.
                intent_id = session.get('payment_intent')
                intent = _stripe(stripe.PaymentIntent.retrieve, intent_id) if intent_id else None
                if not intent or intent.get('status') not in ('canceled', 'requires_payment_method'):
                    raise PurchaseError('Payment is still processing. Your cancellation request is saved; please retry shortly.')
        was_paid = bool(purchase.paid_at) if is_commission(purchase) else purchase.paid
        if was_paid and not payment_intents:
            raise PurchaseError('The payment reference is missing. Please contact support; work is blocked.')
        for intent in sorted(payment_intents):
            _refund(purchase, intent)
        if not done:
            now = timezone.now()
            if is_commission(purchase):
                CommissionStatusHistory.objects.create(
                    commission=purchase, from_status=purchase.status,
                    to_status='canceled', changed_by=user,
                    note='Commission cancelled by the artist.' if user.pk == purchase.receiver_id else 'Buyer cancelled before work started.',
                )
                purchase.status = 'canceled'
                purchase.canceled_at = now
            else:
                # Only webhook-confirmed payments deducted inventory.
                if purchase.paid:
                    for item in purchase.items.order_by('artwork_id', 'pk'):
                        Artwork.objects.filter(pk=item.artwork_id).update(stock=F('stock') + item.quantity)
                purchase.status = 'cancelled'
                purchase.cancelled_at = now
            purchase.save()
        return purchase


def confirm_payment(model, pk, session):
    """Idempotent webhook transition; cancelled purchases never resume work."""
    with transaction.atomic():
        purchase = model.objects.select_for_update().get(pk=pk)
        if session.get('payment_status') != 'paid':
            return
        if session.get('client_reference_id') != reference(purchase):
            raise PurchaseError('Payment reference does not match.')
        expected = purchase.price if is_commission(purchase) else purchase.get_grand_total()
        if session.get('currency') != 'usd' or session.get('amount_total') != int(expected * 100):
            raise PurchaseError('Payment amount or currency does not match.')
        intent = session.get('payment_intent')
        if not intent:
            raise PurchaseError('Missing payment reference.')
        if closed(purchase):
            _refund(purchase, intent)
            # No stock decrement or fulfillment change for a late payment.
            return
        if is_paid(purchase):
            if purchase.stripe_payment_intent_id and purchase.stripe_payment_intent_id != intent:
                _refund(purchase, intent)  # An older, second checkout was also paid.
            return
        purchase.stripe_payment_intent_id = intent
        if is_commission(purchase):
            purchase.paid_at = timezone.now()
            purchase.status = CustomRequest.STATUS_AWAITING_ARTIST
            CommissionStatusHistory.objects.create(
                commission=purchase, from_status='awaiting_payment',
                to_status=CustomRequest.STATUS_AWAITING_ARTIST,
                note='Payment confirmed. Waiting for the artist to start work.',
            )
        else:
            for item in purchase.items.order_by('artwork_id', 'pk'):
                if not Artwork.objects.filter(pk=item.artwork_id, stock__gte=item.quantity).update(stock=F('stock') - item.quantity):
                    raise PurchaseError('Insufficient stock for this payment; manual review required.')
            purchase.paid = True
            purchase.status = 'processing'
        purchase.save()


def update_refund(refund):
    intent = refund.get('payment_intent')
    if not intent:
        return
    ref = (refund.get('metadata') or {}).get('cancellation_reference', '')
    for model in (Order, CustomRequest):
        criteria = Q(cancellation_refunds__has_key=intent)
        if model is Order and ref and not ref.startswith('commission:'):
            criteria |= Q(order_number=ref)
        elif model is CustomRequest and ref.startswith('commission:'):
            commission_id = ref.split(':', 1)[1]
            if commission_id.isdigit():
                criteria |= Q(pk=int(commission_id))
        # Matching by reference also locks the parent while the first refund is
        # still being committed; an early refund event must not be lost merely
        # because its ID has not yet been persisted in the ledger.
        with transaction.atomic():
            for purchase in model.objects.select_for_update().filter(criteria):
                ledger = dict(purchase.cancellation_refunds)
                recorded = ledger.get(intent)
                if (recorded and recorded['id'] == refund.get('id')) or (not recorded and purchase.cancellation_requested_at):
                    ledger[intent] = {'id': refund.get('id'), 'status': refund.get('status')}
                    purchase.cancellation_refunds = ledger
                    purchase.save(update_fields=['cancellation_refunds'])
