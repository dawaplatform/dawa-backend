from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from DawaApp.models import Category, Item, SubCategory
from feed.service import bump_version


# Categories are cached with the feed version, so their edits must invalidate it too.
@receiver(post_save, sender=Item)
@receiver(post_delete, sender=Item)
@receiver(post_save, sender=Category)
@receiver(post_delete, sender=Category)
@receiver(post_save, sender=SubCategory)
@receiver(post_delete, sender=SubCategory)
def _invalidate_feed(sender, **kwargs) -> None:
    bump_version()
