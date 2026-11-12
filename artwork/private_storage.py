"""Filesystem storage for commission uploads, outside all public media roots."""
import os
import posixpath
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage
from django.urls import reverse
from django.utils.deconstruct import deconstructible

PRIVATE_PREFIXES = frozenset({'commission_refs', 'commission_messages', 'commission_deliveries'})


def private_name(name):
    name = str(name)
    parts = PurePosixPath(name).parts
    if (
        not parts or parts[0] not in PRIVATE_PREFIXES or len(parts) < 2
        or name.startswith('/') or '\\' in name or '..' in parts
        or str(PurePosixPath(name)) != name or '\x00' in name
    ):
        raise SuspiciousFileOperation('Invalid commission file name.')
    return name


def public_root():
    return Path(settings.MEDIA_ROOT).resolve()


def private_root():
    root = Path(getattr(settings, 'PRIVATE_MEDIA_ROOT', Path(settings.BASE_DIR) / 'private_media')).resolve()
    roots = [settings.MEDIA_ROOT, getattr(settings, 'STATIC_ROOT', None)]
    for item in getattr(settings, 'STATICFILES_DIRS', []):
        roots.append(item[1] if isinstance(item, (tuple, list)) else item)
    for value in roots:
        if value and root.is_relative_to(Path(value).resolve()):
            raise ImproperlyConfigured('PRIVATE_MEDIA_ROOT must be outside MEDIA_ROOT, STATIC_ROOT and STATICFILES_DIRS.')
    return root


def legacy_path(name):
    name = private_name(name)
    root = public_root()
    candidate = root / name
    if not candidate.resolve().is_relative_to(root):
        raise SuspiciousFileOperation('Invalid legacy commission file path.')
    return candidate


@deconstructible
class PrivateCommissionStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(file_permissions_mode=0o600, directory_permissions_mode=0o700)

    @property
    def base_location(self):
        return str(private_root())

    @property
    def location(self):
        return str(private_root())

    def path(self, name):
        name = private_name(name)
        root = private_root()
        candidate = root / name
        if not candidate.resolve().is_relative_to(root):
            raise SuspiciousFileOperation('Invalid private commission file path.')
        return str(candidate)

    def get_available_name(self, name, max_length=None):
        name = private_name(name)
        candidate = super().get_available_name(name, max_length=max_length)
        # New uploads must not reuse the name of a not-yet-moved legacy upload.
        # That could make two different commissions refer to different bytes
        # under the same key while legacy files are being relocated.
        while legacy_path(candidate).exists():
            directory, filename = posixpath.split(candidate)
            file_root, extension = os.path.splitext(filename)
            candidate = super().get_available_name(
                posixpath.join(directory, self.get_alternative_name(file_root, extension)),
                max_length=max_length,
            )
        return candidate

    def _open(self, name, mode='rb'):
        try:
            return super()._open(private_name(name), mode)
        except FileNotFoundError:
            # Only the authenticated file view exposes this fallback to HTTP.
            # It keeps existing commissions usable during the verified move.
            from django.core.files import File
            return File(open(legacy_path(name), mode))

    def url(self, name):
        return reverse('commission_file', kwargs={'file_name': private_name(name)})


private_commission_storage = PrivateCommissionStorage()
