from django.apps import AppConfig


class DawaappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'DawaApp'

    def ready(self):
        # Wire up model-level safety-net signals.
        from . import signals  # noqa: F401
