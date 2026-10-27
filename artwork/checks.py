from django.core.checks import Error, register
from django.core.exceptions import ImproperlyConfigured
from .private_storage import private_root


@register()
def check_private_commission_root(app_configs, **kwargs):
    try:
        private_root()
    except ImproperlyConfigured as exc:
        return [Error(str(exc), id='artwork.E001')]
    return []
