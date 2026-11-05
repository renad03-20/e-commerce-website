"""Multipart purchase emails. Return False on failure without interrupting payment."""
import logging
from urllib.parse import urljoin, urlsplit, urlunsplit

from decouple import config
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.urls import reverse

from .cancellation import closed

logger = logging.getLogger(__name__)


def _site_url(site_url):
    if not site_url:
        site_url = config('SITE_DOMAIN', default='127.0.0.1:8001')
        if '://' not in site_url:
            site_url = ('http://' if settings.DEBUG else 'https://') + site_url
    parts = urlsplit(site_url)
    if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password:
        raise ValueError('Configure a valid HTTP(S) site address for purchase emails.')
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/') + '/', '', ''))


def _send_message(subject, recipient, template, context, description):
    try:
        validate_email(recipient)
        text = render_to_string(f'orders/emails/{template}.txt', context).strip()
        html = render_to_string(f'orders/emails/{template}.html', context)
        message = EmailMultiAlternatives(
            subject=subject, body=text, from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        message.attach_alternative(html, 'text/html')
        if message.send(fail_silently=False) != 1:
            logger.error('Email backend did not accept %s.', description)
            return False
    except Exception:
        logger.exception('Could not send %s.', description)
        return False
    logger.info('Sent %s.', description)
    return True


def send_order_confirmation(order, site_url=None):
    if not order.paid or closed(order):
        return False
    try:
        order_url = urljoin(_site_url(site_url), reverse('order_detail', args=[order.order_number]))
    except Exception:
        logger.exception('Could not build the buyer email link for order %s.', order.pk)
        return False
    return _send_message(
        f'Order confirmation - {order.order_number} - Artsy', order.email,
        'order_confirmation', {'order': order, 'order_url': order_url},
        f'buyer confirmation for order {order.order_number}',
    )


def send_artist_order_notification(order_item, site_url=None):
    order = order_item.order
    if not order.paid or closed(order):
        return False
    artist = order_item.artwork.artist
    try:
        order_url = urljoin(_site_url(site_url), reverse('artist_order_detail', args=[order.order_number]))
    except Exception:
        logger.exception('Could not build the artist email link for order item %s.', order_item.pk)
        return False
    return _send_message(
        f'Artwork purchased - {order.order_number} - Artsy', artist.email,
        'artist_notification', {'order_item': order_item, 'order': order, 'artist': artist, 'order_url': order_url},
        f'artist notification for order item {order_item.pk}',
    )
