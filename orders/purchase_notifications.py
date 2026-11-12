"""Queue verified purchase emails and deliver them outside the webhook request."""
import logging
from collections import Counter
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from .cancellation import closed
from .emails import send_artist_order_notification, send_order_confirmation
from .models import PurchaseEmailJob

logger = logging.getLogger(__name__)
State = PurchaseEmailJob.State
MAX_ATTEMPTS = 5


def queue_purchase_emails(order):
    """Called once, inside the transaction that records payment and deducts stock."""
    now = timezone.now()
    jobs = [PurchaseEmailJob(order=order, key=f'buyer:{order.pk}', available_at=now)]
    for item in order.items.select_related('artwork').all():
        jobs.append(PurchaseEmailJob(
            order=order, item=item, key=f'artist:{item.pk}', available_at=now,
            artist_id_at_payment=item.artwork.artist_id,
        ))
    PurchaseEmailJob.objects.bulk_create(jobs)


def deliver_due_purchase_emails(limit=100):
    results = Counter()
    due = PurchaseEmailJob.objects.filter(state=State.PENDING, available_at__lte=timezone.now())
    job_ids = list(due.order_by('available_at', 'pk').values_list('pk', flat=True)[:limit])
    for pk in job_ids:
        now = timezone.now()
        claimed = PurchaseEmailJob.objects.filter(
            pk=pk, state=State.PENDING, available_at__lte=now,
        ).update(state=State.SENDING, claimed_at=now, attempts=F('attempts') + 1)
        if not claimed:
            continue
        job = PurchaseEmailJob.objects.select_related('order', 'item__artwork__artist').filter(pk=pk).first()
        if job is None:
            continue
        state = _deliver(job)
        results[state] += 1
    return results


def _deliver(job):
    order = job.order
    item = job.item
    if not order.paid or closed(order) or (
        item is not None and (
            item.order_id != order.pk or item.artwork.artist_id != job.artist_id_at_payment
        )
    ):
        job.state = State.SKIPPED
    else:
        try:
            delivered = (
                send_order_confirmation(order) if item is None
                else send_artist_order_notification(item)
            )
        except Exception:
            logger.exception('Purchase email job %s failed.', job.pk)
            delivered = False
        if delivered:
            job.state = State.SENT
            job.sent_at = timezone.now()
        elif job.attempts >= MAX_ATTEMPTS:
            job.state = State.FAILED
        else:
            job.state = State.PENDING
            job.available_at = timezone.now() + timedelta(minutes=2 ** (job.attempts - 1))

    # UPDATE rather than save: a deleted order or item must not resurrect this job.
    PurchaseEmailJob.objects.filter(
        pk=job.pk, state=State.SENDING, claimed_at=job.claimed_at,
    ).update(
        state=job.state, sent_at=job.sent_at, claimed_at=None, available_at=job.available_at,
    )
    return job.state
