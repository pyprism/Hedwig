from celery import shared_task
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from hedwig.models import (
    EmailMessage,
    Mailbox,
    OutboundSendAttempt,
    SuppressedAddress,
    UserMailboxAccess,
)
from providers.postmark import TransientSendError
from providers.sending import send_with_provider
from utils.enums import EmailStatus, SendAttemptStatus


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_message_task(self, message_id, attempt_id):
    """
    Send one queued outbound message attempt.
    The API creates the message/attempt; Celery owns provider IO and status updates.

    Transient errors (network issues, Postmark 5xx) are retried; permanent errors
    (validation, Postmark 4xx, daily limit) mark the attempt failed immediately.
    """

    try:
        attempt = reserve_attempt_for_sending(attempt_id)
        if attempt is None:
            return {"status": "skipped", "attempt_id": str(attempt_id)}

        message = attempt.message
        send_with_provider(message, attempt)
        return {
            "status": "sent",
            "attempt_id": str(attempt_id),
            "message_id": str(message_id),
        }
    except TransientSendError as exc:
        raise self.retry(exc=exc)
    except ValidationError as exc:
        mark_attempt_failed(attempt_id, "validation_error", "; ".join(exc.messages))
        return {"status": "failed", "attempt_id": str(attempt_id)}
    except Exception as exc:
        mark_attempt_failed(attempt_id, exc.__class__.__name__, str(exc))
        raise


def reserve_attempt_for_sending(attempt_id):
    with transaction.atomic():
        attempt = (
            OutboundSendAttempt.objects.select_for_update()
            .select_related("message", "provider")
            .get(pk=attempt_id)
        )
        if attempt.status in {
            SendAttemptStatus.SENDING,
            SendAttemptStatus.SENT,
            SendAttemptStatus.CANCELLED,
        }:
            return None

        attempt.status = SendAttemptStatus.SENDING
        attempt.started_at = timezone.now()
        attempt.save(update_fields=["status", "started_at"])
        return attempt


def mark_attempt_failed(attempt_id, code, message):
    with transaction.atomic():
        attempt = (
            OutboundSendAttempt.objects.select_for_update()
            .select_related("message")
            .filter(pk=attempt_id)
            .first()
        )
        if attempt is None or attempt.status == SendAttemptStatus.SENT:
            return

        attempt.status = SendAttemptStatus.FAILED
        attempt.error_code = code[:100]
        attempt.error_message = message
        attempt.finished_at = timezone.now()
        attempt.save(
            update_fields=["status", "error_code", "error_message", "finished_at"]
        )

        attempt.message.status = EmailStatus.FAILED
        attempt.message.save(update_fields=["status", "updated_at"])


@shared_task
def expire_user_mailbox_access_task():
    """Beat entry point: deactivate UserMailboxAccess grants past their expires_at."""
    expired = UserMailboxAccess.objects.filter(
        is_active=True, expires_at__isnull=False, expires_at__lte=timezone.now()
    ).update(is_active=False)
    return {"expired": expired}


@shared_task
def expire_suppressed_addresses_task():
    """Beat entry point: drop SuppressedAddress rows past their expires_at."""
    deleted, _ = SuppressedAddress.objects.filter(
        expires_at__isnull=False, expires_at__lte=timezone.now()
    ).delete()
    return {"deleted": deleted}


@shared_task
def reconcile_mailbox_used_bytes_task():
    """Beat entry point: recompute Mailbox.used_bytes from stored message sizes."""
    totals = dict(
        EmailMessage.objects.values("mailbox_id")
        .annotate(total=models.Sum("size_bytes"))
        .values_list("mailbox_id", "total")
    )
    updated = 0
    for mailbox in Mailbox.objects.all():
        total = totals.get(mailbox.id) or 0
        if mailbox.used_bytes != total:
            Mailbox.objects.filter(pk=mailbox.pk).update(used_bytes=total)
            updated += 1
    return {"updated": updated}
