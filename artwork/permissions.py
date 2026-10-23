"""Artist eligibility used by public profiles and commission management."""
from django.contrib.auth import get_user_model
from django.db.models import Q


def is_artist_account(user):
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.is_superuser or user.groups.filter(name='Artists').exists())
    )


def artist_accounts():
    return (
        get_user_model().objects.filter(is_active=True)
        .filter(Q(groups__name='Artists') | Q(is_superuser=True))
        .select_related('userprofile')
        .distinct()
    )
