from django.apps import AppConfig


class ArtworkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'artwork'

    def ready(self):
        from . import checks  # Register the private-storage configuration check.
