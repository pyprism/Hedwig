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


def record_send_failure(domain):
    """Record a confirmed send failure against today's ``DailyDomainSendLog``.

    Called once per message, only after the provider call resolves. The
    matching success case doesn't need a separate call: a successful send's
    slot was already counted by ``reserve_send_slot`` up front.
    """
    today = timezone.now().date()
    with transaction.atomic():
        log, _ = DailyDomainSendLog.objects.select_for_update().get_or_create(
            domain=domain, date=today
        )
        log.failed_count = models.F("failed_count") + 1
        log.save(update_fields=["failed_count"])


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

    # send_enabled/outbound_enabled are only checked at compose time
    # (SendEmailSerializer scopes the choosable mailbox to send_enabled()).
    # A message can sit queued for a while (retry backoff, a scheduled_at
    # days out) during which an admin may disable sending — re-check here,
    # at actual dispatch time, not just at compose time.
    if not message.mailbox.send_enabled or not domain.outbound_enabled:
        error = "Sending is disabled for this mailbox or domain."
        mark_send_failed(message, attempt, "send_disabled", error)
        raise PermanentSendError(error)

    suppressed = recheck_suppressed_recipients(message)
    if suppressed:
        error = f"Recipient(s) suppressed: {', '.join(sorted(suppressed))}"
        mark_send_failed(message, attempt, "recipient_suppressed", error)
        raise PermanentSendError(error)

    limit = get_daily_send_limit(domain)
    if not DailyDomainSendLog.objects.reserve_send_slot(domain, limit):
        record_send_failure(domain)
        mark_send_failed(
            message,
            attempt,
            "daily_limit_exceeded",
            "Daily send limit reached for this domain.",
        )
        raise PermanentSendError("Daily send limit reached for this domain.")

    try:
        materialize_attachments(message)
        provider_impl = get_provider(message.provider or domain.provider)
        result = provider_impl.send(message, attempt)
    except TransientSendError:
        # Caller retries this same attempt (a fresh call reserves its own
        # slot), so give back the reservation this call made. Covers both
        # a provider-level transient failure and materialize_attachments
        # raising before the provider is ever called (e.g. storage outage) —
        # either way the reserved slot must not leak.
        DailyDomainSendLog.objects.release_send_slot(domain)
        raise
    except PermanentSendError:
        DailyDomainSendLog.objects.release_send_slot(domain)
        record_send_failure(domain)
        raise
    return result
