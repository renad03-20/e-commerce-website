"""Authenticated commission file delivery and blocking of old public URLs."""
import posixpath
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousFileOperation
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseForbidden, HttpResponseNotFound
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.views.decorators.vary import vary_on_cookie

from .models import CustomRequest, CommissionMessage, CommissionDelivery
from .private_storage import PRIVATE_PREFIXES, private_commission_storage, private_name


def legacy_private_request(path):
    media_prefix = '/' + urlsplit(settings.MEDIA_URL).path.strip('/') + '/'
    path = '/' + posixpath.normpath(unquote(path).replace('\\', '/')).lstrip('/')
    if not path.startswith(media_prefix):
        return False
    relative = path[len(media_prefix):]
    return relative.split('/', 1)[0].casefold() in PRIVATE_PREFIXES


class LegacyCommissionMediaGuard:
    """Runs before Django's development media server, for all DEBUG settings."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if legacy_private_request(request.path_info):
            response = HttpResponseNotFound('This file is available only through its commission page.')
            patch_cache_control(response, private=True, no_store=True, max_age=0)
            return response
        return self.get_response(request)


def _safe_image_type(stream):
    header = stream.read(16)
    stream.seek(0)
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if header.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if header.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return 'image/webp'
    return None


@never_cache
@vary_on_cookie
@login_required
@require_safe
def commission_file(request, file_name):
    try:
        file_name = private_name(file_name)
    except SuspiciousFileOperation:
        raise Http404
    prefix = PurePosixPath(file_name).parts[0]
    if prefix == 'commission_refs':
        allowed = CustomRequest.objects.filter(reference_image=file_name).filter(
            Q(sender_id=request.user.pk) | Q(receiver_id=request.user.pk),
        ).exists()
    else:
        model, field = (
            (CommissionMessage, 'attachment') if prefix == 'commission_messages'
            else (CommissionDelivery, 'delivery_file')
        )
        allowed = model.objects.filter(**{field: file_name}).filter(
            Q(commission__sender_id=request.user.pk) | Q(commission__receiver_id=request.user.pk),
        ).exists()
    if not allowed:
        return HttpResponseForbidden("You don't have permission to access this commission file.")
    try:
        stream = private_commission_storage.open(file_name, 'rb')
    except (FileNotFoundError, SuspiciousFileOperation):
        raise Http404
    try:
        image_type = _safe_image_type(stream) if prefix == 'commission_refs' else None
        response = FileResponse(
            stream, as_attachment=not bool(image_type),
            filename=PurePosixPath(file_name).name,
            content_type=image_type or 'application/octet-stream',
        )
    except BaseException:
        stream.close()
        raise
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
    response['Referrer-Policy'] = 'no-referrer'
    return response
