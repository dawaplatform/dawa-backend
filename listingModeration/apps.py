from django.apps import AppConfig


class ListingModerationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "listingModeration"
    verbose_name = "Listing Moderation"

    def ready(self) -> None:
        from . import signals  # noqa: F401
