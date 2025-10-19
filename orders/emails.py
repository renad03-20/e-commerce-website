from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings

def send_order_confirmation(order):
    subject = f'order confirmation - #{order.id} - artsy'

    context = {
        'order': order,
        'site_url': 'http://127.0.0.1:8000'
    }

    html_content = render_to_string('email/order_confirmation.html', context)
    text_contect = strip_tags(html_content)

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_contect,
        from_email='noreply@artsy.com',
        to=[order.emial]
    )
    email.attach_alternative(html_content, 'text/html')

    try:
        email.send()
        print(f'Order confirmation email send to {order.email}')
        return True
    except Exception as e:
        print(f'Failed to send email: {e}')
        return False
    
def send_artist_order_notification(order_item):
    artist = order_item.artwork.artist