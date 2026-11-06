from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from DawaApp.models import Item
from feed.service import bump_version


@receiver(post_save, sender=Item)
@receiver(post_delete, sender=Item)
def _invalidate_feed(sender, **kwargs) -> None:
    bump_version()
