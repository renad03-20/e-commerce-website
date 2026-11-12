from django.conf import settings
from django.core.mail import send_mail


def send_commission_email(subject, message, to_email):
    """
    Lightweight email helper for commission updates.
    """
    if not to_email:
        return False
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=True,
        )
        return True
    except Exception as exc:
        print(f"Commission email failed: {exc}")
        return False
