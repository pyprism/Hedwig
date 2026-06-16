from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.db.models.signals import post_delete
from django.dispatch import receiver

from hedwig.models import EmailMessage, Mailbox


@receiver(post_delete, sender=EmailMessage)
def decrement_mailbox_used_bytes(sender, instance, **kwargs):
    """Keep Mailbox.used_bytes in sync when a stored message is deleted."""
    if not instance.size_bytes:
        return
    Mailbox.objects.filter(pk=instance.mailbox_id).update(
        used_bytes=Greatest(F("used_bytes") - instance.size_bytes, Value(0))
    )
