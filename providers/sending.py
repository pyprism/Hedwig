"""Generic outbound send helpers shared across provider implementations."""

from django.db import models, transaction
from django.utils import timezone

from hedwig.models import SuppressedAddress
from providers.models import DailyDomainSendLog
from providers.postmark import PermanentSendError, TransientSendError, mark_send_failed
from providers.registry import get_provider
from utils.attachments import store_attachment_content


def get_daily_send_limit(domain):
    """Return the effective daily send limit for ``domain``, or None if unlimited."""
    limits = [
        limit
        for limit in (domain.max_send_per_day, domain.provider.max_send_per_day)
        if limit
    ]
    return min(limits) if limits else None


def daily_send_limit_reached(domain):
    """Check (without reserving) whether ``domain`` has hit its daily send limit."""
    limit = get_daily_send_limit(domain)
    if limit is None:
        return False
    today = timezone.now().date()
    log = DailyDomainSendLog.objects.filter(domain=domain, date=today).first()
    sent_count = log.sent_count if log else 0
    return sent_count >= limit


def record_send_result(domain, success):
    """Record a confirmed send outcome against today's ``DailyDomainSendLog``.

    Called once per message, only after the provider call resolves, so retries
    of the same attempt don't inflate the count and permanently-failed sends
    don't count against the limit.
    """
    today = timezone.now().date()
    field = "sent_count" if success else "failed_count"
    with transaction.atomic():
        log, _ = DailyDomainSendLog.objects.select_for_update().get_or_create(
            domain=domain, date=today
        )
        setattr(log, field, models.F(field) + 1)
        log.save(update_fields=[field])


def recheck_suppressed_recipients(message):
    """Return the subset of ``message``'s recipients suppressed at send time."""
    emails = {
        row["email"]
        for row in message.to_addresses + message.cc_addresses + message.bcc_addresses
    }
    return SuppressedAddress.objects.suppressed_emails(message.mailbox, emails)


def materialize_attachments(message):
    """Upload any attachments still holding pending base64 content to S3."""
    total_size = 0
    has_attachments = False
    for attachment in message.attachments.all():
        has_attachments = True
        pending_content_b64 = attachment.metadata.get("pending_content_b64")
        if pending_content_b64 and not attachment.file:
            file_url, storage_key, checksum, size_bytes = store_attachment_content(
                message.mailbox_id, attachment.filename, pending_content_b64
            )
            if not file_url:
                raise TransientSendError(
                    f"Could not store attachment '{attachment.filename}' before sending."
                )
            attachment.file = file_url
            attachment.storage_key = storage_key
            attachment.checksum_sha256 = checksum or None
            attachment.size_bytes = size_bytes
            attachment.metadata = {
                key: value
                for key, value in attachment.metadata.items()
                if key != "pending_content_b64"
            }
            attachment.save(
                update_fields=[
                    "file",
                    "storage_key",
                    "checksum_sha256",
                    "size_bytes",
                    "metadata",
                ]
            )
        total_size += attachment.size_bytes

    if has_attachments:
        message.size_bytes = total_size
        message.save(update_fields=["size_bytes", "updated_at"])


def send_with_provider(message, attempt):
    """Reserve a send slot and dispatch ``message`` through its provider."""
    domain = message.mailbox.domain

    suppressed = recheck_suppressed_recipients(message)
    if suppressed:
        error = f"Recipient(s) suppressed: {', '.join(sorted(suppressed))}"
        mark_send_failed(message, attempt, "recipient_suppressed", error)
        raise PermanentSendError(error)

    if daily_send_limit_reached(domain):
        record_send_result(domain, success=False)
        mark_send_failed(
            message,
            attempt,
            "daily_limit_exceeded",
            "Daily send limit reached for this domain.",
        )
        raise PermanentSendError("Daily send limit reached for this domain.")

    materialize_attachments(message)

    provider_impl = get_provider(message.provider or domain.provider)
    try:
        result = provider_impl.send(message, attempt)
    except TransientSendError:
        # Retried by the caller without re-reserving a slot; don't record yet.
        raise
    except PermanentSendError:
        record_send_result(domain, success=False)
        raise
    record_send_result(domain, success=True)
    return result
