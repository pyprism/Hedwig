from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.db.models.signals import post_delete
from django.dispatch import receiver

from hedwig.models import EmailAttachment, EmailMessage, Mailbox


@receiver(post_delete, sender=EmailMessage)
def decrement_mailbox_used_bytes(sender, instance, **kwargs):
    """Keep Mailbox.used_bytes in sync when a stored message is deleted."""
    if not instance.size_bytes:
        return
    Mailbox.objects.filter(pk=instance.mailbox_id).update(
        used_bytes=Greatest(F("used_bytes") - instance.size_bytes, Value(0))
    )


@receiver(post_delete, sender=EmailAttachment)
def delete_attachment_file(sender, instance, **kwargs):
    """Enqueue S3 cleanup for an attachment after the DB delete commits."""
    if not instance.file:
        return

    storage_key = instance.storage_key
    file_url = instance.file

    def enqueue_cleanup():
        from hedwig.tasks import delete_unreferenced_attachment_file_task

        delete_unreferenced_attachment_file_task.delay(file_url, storage_key)

    transaction.on_commit(enqueue_cleanup)
