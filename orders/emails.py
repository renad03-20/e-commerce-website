from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site
from decouple import config


def send_order_confirmation(order):
    """Send order confirmation email to customer"""
    subject = f'Order Confirmation - #{order.id} - Art Gallery'

    domain = config('SITE_DOMAIN', default='localhost:8000')
    
    # Create HTML email content
    context = {
        'order': order,
        'site_url': f"http://{domain}"
    }
    
    html_content = render_to_string('emails/order_confirmation.html', context)
    text_content = strip_tags(html_content)  # Plain text version
    
    # Create email
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[order.email]
    )
    email.attach_alternative(html_content, "text/html")
    
    try:
        email.send()
        print(f"Order confirmation email sent to {order.email}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def send_artist_order_notification(order_item):
    """Send notification to artist when their artwork is purchased"""
    artist = order_item.artwork.artist
    subject = f'🎨 Your artwork was purchased! - {order_item.artwork_title}'

    domain = config('SITE_DOMAIN', default='localhost:8000')
    
    context = {
        'order_item': order_item,
        'artist': artist,
        'site_url': f"http://{domain}"
    }
    
    html_content = render_to_string('emails/artist_notification.html', context)
    text_content = strip_tags(html_content)
    
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[artist.email]
    )
    email.attach_alternative(html_content, "text/html")
    
    try:
        email.send()
        print(f"Artist notification sent to {artist.email}")
        return True
    except Exception as e:
        print(f"Failed to send artist email: {e}")
        return False
