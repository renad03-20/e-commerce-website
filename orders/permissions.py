"""Role checks for artist order management, with the site's friendly banners."""
from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from artwork.permissions import is_artist_account


def artist_required(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not is_artist_account(request.user):
            messages.error(request, 'Only artist accounts can access order management.')
            return redirect('order_list')
        return view(request, *args, **kwargs)
    return guarded
