"""
Model-level safety net.

Any code path that creates a Message (view, admin, shell, third-party integration,
etc.) runs this post_save hook. We use only the fast local prescreen here so every
insert stays cheap — the AI check happens up-front in the SendMessage view. If a
saved Message matches an obvious profanity/scam pattern, we delete it immediately.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Message
from .services import local_prescreen

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Message)
def enforce_message_safety(sender, instance, created, **kwargs):
    if not created:
        return

    result = local_prescreen(instance.message or "")
    if not result["is_safe"]:
        logger.warning(
            "Deleting unsafe Message id=%s reason=%s preview=%.60s",
            instance.id, result["reason"], instance.message or "",
        )
        Message.objects.filter(pk=instance.pk).delete()
