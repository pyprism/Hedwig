"""Provider-agnostic webhook ingestion.

Operates on the normalized dataclasses from ``providers.base`` (see
``ParsedWebhookEvent``) so the same logic processes inbound mail and delivery
events regardless of which provider the webhook came from. The entry point is
``process_webhook_log``, which takes a stored ``ProviderWebhookLog`` row.
"""

import logging
import re

from django.db import models, transaction
from django.utils import timezone

from hedwig.models import (
    EmailAttachment,
    EmailMessage,
    EmailRecipient,
    EmailThread,
    Mailbox,
    MailboxAlias,
    SuppressedAddress,
)
from hedwig.rules import evaluate_rules, forward_message
from providers.models import DeliveryEvent
from providers.registry import get_provider
from utils.attachments import store_attachment_content
from utils.enums import (
    DirectionType,
    EmailStatus,
    EventType,
    Folder,
    ProviderWebhookStatus,
    RecipientType,
)


logger = logging.getLogger(__name__)

REPLY_PREFIX_PATTERN = re.compile(r"^(re|fwd?|fw)\s*:\s*", re.IGNORECASE)

SPAM_SCORE_THRESHOLD = 5.0


class MailboxQuotaExceeded(Exception):
    """Raised when an inbound message would push a mailbox over its storage quota."""


def estimate_inbound_message_size(normalized):
    """Fallback byte estimate when a provider does not include MessageSize."""
    parts = [
        normalized.from_address,
        normalized.from_name,
        normalized.envelope_sender,
        normalized.envelope_recipient,
        normalized.reply_to,
        normalized.subject,
        normalized.body_text,
        normalized.body_html,
        normalized.rfc_message_id or "",
        normalized.in_reply_to or "",
        normalized.references or "",
    ]
    parts.extend(row.email for row in normalized.to)
    parts.extend(row.email for row in normalized.cc)
    parts.extend(row.email for row in normalized.bcc)
    parts.extend(f"{key}: {value}" for key, value in normalized.raw_headers.items())
    return len("\n".join(part for part in parts if part).encode("utf-8"))


def normalize_subject(subject):
    subject = (subject or "").strip()
    while True:
        match = REPLY_PREFIX_PATTERN.match(subject)
        if not match:
            return subject
        subject = subject[match.end() :].strip()


def resolve_mailbox(domain, normalized):
    """Find the (Mailbox, recipient_email) an inbound message should be delivered to."""
    envelope_recipient = (normalized.envelope_recipient or "").strip().lower()
    recipient_emails = []
    if envelope_recipient:
        recipient_emails.append(envelope_recipient)
    recipient_emails.extend(
        recipient.email for recipient in normalized.to + normalized.cc + normalized.bcc
    )

    for recipient_email in recipient_emails:
        local_part, _, recipient_domain = recipient_email.partition("@")
        if recipient_domain.lower() != domain.name.lower():
            continue

        mailbox = Mailbox.objects.filter(
            domain=domain,
            local_part__iexact=local_part,
            is_active=True,
            receive_enabled=True,
        ).first()
        if mailbox:
            return mailbox, recipient_email

        alias = (
            MailboxAlias.objects.filter(
                domain=domain,
                local_part__iexact=local_part,
                is_active=True,
                can_receive=True,
            )
            .select_related("mailbox")
            .first()
        )
        if alias:
            return alias.mailbox, recipient_email

    catch_all = Mailbox.objects.filter(
        domain=domain, is_catch_all=True, is_active=True, receive_enabled=True
    ).first()
    if catch_all:
        recipient_email = (
            recipient_emails[0] if recipient_emails else normalized.envelope_recipient
        )
        return catch_all, recipient_email

    return None, ""


def update_thread_for_message(mailbox, message):
    """Attach ``message`` to an existing thread (matched by headers/subject) or start a new one."""
    thread = message.thread
    candidate_ids = []
    if message.in_reply_to:
        candidate_ids.append(message.in_reply_to)
    candidate_ids.extend((message.references or "").split())

    if thread is None and candidate_ids:
        thread = EmailThread.objects.filter(
            mailbox=mailbox, root_message_id__in=candidate_ids
        ).first()
        if thread is None:
            thread = (
                EmailThread.objects.filter(
                    mailbox=mailbox, messages__rfc_message_id__in=candidate_ids
                )
                .order_by("-last_message_at")
                .first()
            )

    normalized_subject = normalize_subject(message.subject)
    if thread is None and normalized_subject:
        thread = (
            EmailThread.objects.filter(
                mailbox=mailbox, normalized_subject=normalized_subject
            )
            .order_by("-last_message_at")
            .first()
        )

    participants = {message.from_address}
    participants.update(
        row["email"]
        for row in message.to_addresses + message.cc_addresses + message.bcc_addresses
    )

    occurred_at = message.received_at or message.sent_at or timezone.now()

    if thread is None:
        thread = EmailThread.objects.create(
            mailbox=mailbox,
            subject=message.subject,
            normalized_subject=normalized_subject,
            root_message_id=message.rfc_message_id or "",
            participants=sorted(participants),
            last_message_at=occurred_at,
        )

    if message.thread_id != thread.id:
        message.thread = thread
        message.save(update_fields=["thread"])

    thread.participants = sorted(set(thread.participants or []) | participants)
    thread.message_count = models.F("message_count") + 1
    if message.direction == DirectionType.INBOUND:
        thread.has_unread = True
    thread.last_message_at = occurred_at
    if not thread.root_message_id and message.rfc_message_id:
        thread.root_message_id = message.rfc_message_id
    thread.save(
        update_fields=[
            "participants",
            "message_count",
            "has_unread",
            "last_message_at",
            "root_message_id",
        ]
    )
    return thread


def create_inbound_message(provider, mailbox, recipient_email, normalized, raw_webhook):
    """Persist a normalized inbound message, or return the existing one if already ingested."""
    if normalized.provider_message_id:
        existing = EmailMessage.objects.filter(
            provider=provider,
            provider_message_id=normalized.provider_message_id,
            direction=DirectionType.INBOUND,
        ).first()
        if existing:
            return existing, False

    snippet = (normalized.body_text or "").strip().replace("\n", " ")[:500]
    folder = (
        Folder.SPAM
        if normalized.spam_score is not None
        and normalized.spam_score >= SPAM_SCORE_THRESHOLD
        else Folder.INBOX
    )

    stored_message_size = normalized.size_bytes or estimate_inbound_message_size(
        normalized
    )
    incoming_size = stored_message_size + sum(
        attachment.declared_size for attachment in normalized.attachments
    )
    if mailbox.quota_bytes and mailbox.used_bytes + incoming_size > mailbox.quota_bytes:
        raise MailboxQuotaExceeded(
            f"Mailbox {mailbox.id} quota exceeded "
            f"({mailbox.used_bytes + incoming_size}/{mailbox.quota_bytes} bytes)."
        )

    with transaction.atomic():
        message = EmailMessage.objects.create(
            mailbox=mailbox,
            direction=DirectionType.INBOUND,
            status=EmailStatus.RECEIVED,
            folder=folder,
            rfc_message_id=normalized.rfc_message_id,
            from_address=normalized.from_address,
            from_name=normalized.from_name,
            envelope_sender=normalized.envelope_sender or None,
            envelope_recipient=recipient_email or normalized.envelope_recipient or None,
            to_addresses=[
                {"email": row.email, "name": row.name} for row in normalized.to
            ],
            cc_addresses=[
                {"email": row.email, "name": row.name} for row in normalized.cc
            ],
            bcc_addresses=[
                {"email": row.email, "name": row.name} for row in normalized.bcc
            ],
            reply_to=normalized.reply_to or None,
            subject=normalized.subject,
            in_reply_to=normalized.in_reply_to,
            references=normalized.references,
            body_text=normalized.body_text,
            body_html=normalized.body_html,
            snippet=snippet,
            raw_headers=normalized.raw_headers,
            provider=provider,
            provider_message_id=normalized.provider_message_id,
            size_bytes=stored_message_size,
            spam_score=normalized.spam_score,
            metadata={**normalized.metadata, "auth_results": normalized.auth_results},
            received_at=normalized.received_at,
        )

        for recipient_type, rows in (
            (RecipientType.TO, normalized.to),
            (RecipientType.CC, normalized.cc),
            (RecipientType.BCC, normalized.bcc),
        ):
            EmailRecipient.objects.bulk_create(
                [
                    EmailRecipient(
                        message=message,
                        recipient_type=recipient_type,
                        email=row.email,
                        name=row.name,
                        delivered_to_mailbox=(
                            mailbox if row.email == recipient_email else None
                        ),
                    )
                    for row in rows
                ]
            )

        total_size = stored_message_size
        for attachment in normalized.attachments:
            file_url, storage_key, checksum, size_bytes = store_attachment_content(
                mailbox.id, attachment.filename, attachment.content_b64
            )
            size_bytes = size_bytes or attachment.declared_size
            total_size += size_bytes
            EmailAttachment.objects.create(
                message=message,
                filename=attachment.filename,
                content_type=attachment.content_type,
                size_bytes=size_bytes,
                file=file_url or None,
                storage_key=storage_key or None,
                checksum_sha256=checksum or None,
                content_id=attachment.content_id or None,
                is_inline=attachment.is_inline,
                content_disposition="inline" if attachment.is_inline else "attachment",
            )

        if normalized.attachments:
            message.has_attachments = True
            message.size_bytes = total_size
            message.save(update_fields=["has_attachments", "size_bytes"])

        Mailbox.objects.filter(pk=mailbox.pk).update(
            used_bytes=models.F("used_bytes") + total_size
        )

        update_thread_for_message(mailbox, message)
        evaluate_rules(mailbox, message)
        if mailbox.forward_to:
            forward_message(message, mailbox.forward_to, reason="mailbox_forward_to")

    return message, True


DELIVERY_EVENT_STATUS_MAP = {
    EventType.DELIVERED: EmailStatus.DELIVERED,
    EventType.BOUNCED: EmailStatus.BOUNCED,
    EventType.OPENED: EmailStatus.OPENED,
    EventType.CLICKED: EmailStatus.CLICKED,
    EventType.COMPLAINED: EmailStatus.SPAM,
    EventType.FAILED: EmailStatus.FAILED,
}

# Lifecycle ordering for outbound message/recipient status. A status can only
# move forward (higher rank), so an out-of-order "opened" can't undo a
# "bounced", and a late "delivered" can't undo an "opened".
EMAIL_STATUS_RANK = {
    EmailStatus.QUEUED: 0,
    EmailStatus.SENDING: 1,
    EmailStatus.SENT: 2,
    EmailStatus.DELIVERED: 3,
    EmailStatus.OPENED: 4,
    EmailStatus.CLICKED: 5,
    EmailStatus.BOUNCED: 6,
    EmailStatus.SPAM: 6,
    EmailStatus.FAILED: 6,
    EmailStatus.CANCELLED: 6,
}

SUPPRESSING_EVENT_TYPES = {
    EventType.BOUNCED,
    EventType.COMPLAINED,
    EventType.UNSUBSCRIBED,
}

SUPPRESSION_REASONS = {
    EventType.BOUNCED: "bounce",
    EventType.COMPLAINED: "complaint",
    EventType.UNSUBSCRIBED: "unsubscribe",
}


def create_delivery_event(domain, normalized, raw_webhook):
    """Persist a normalized delivery event against its outbound message, or return None."""
    message = EmailMessage.objects.filter(
        provider_message_id=normalized.provider_message_id,
        direction=DirectionType.OUTBOUND,
    ).first()
    if message is None:
        return None

    event, created = DeliveryEvent.objects.get_or_create(
        message=message,
        event_type=normalized.event_type,
        recipient=normalized.recipient or "",
        provider_event_id=normalized.provider_event_id or "",
        defaults={
            "reason": normalized.reason,
            "link_url": normalized.link_url,
            "occurred_at": normalized.occurred_at or timezone.now(),
            "metadata": normalized.metadata,
            "raw_webhook": raw_webhook,
        },
    )
    if not created:
        return event

    new_status = DELIVERY_EVENT_STATUS_MAP.get(normalized.event_type)
    new_rank = EMAIL_STATUS_RANK.get(new_status, 0)
    if new_status and new_rank > EMAIL_STATUS_RANK.get(message.status, 0):
        message.status = new_status
        message.save(update_fields=["status", "updated_at"])

    if normalized.recipient and new_status:
        not_lower = [
            status for status, rank in EMAIL_STATUS_RANK.items() if rank >= new_rank
        ]
        EmailRecipient.objects.filter(
            message=message, email=normalized.recipient
        ).exclude(status__in=not_lower).update(status=new_status)

    if normalized.event_type in SUPPRESSING_EVENT_TYPES and normalized.recipient:
        SuppressedAddress.objects.get_or_create(
            domain=domain or message.mailbox.domain,
            mailbox=None,
            email=normalized.recipient,
            defaults={
                "reason": SUPPRESSION_REASONS[normalized.event_type],
                "source": "webhook",
                "raw_event": raw_webhook,
            },
        )

    return event


def process_webhook_log(raw_webhook):
    """Parse and apply a stored ``ProviderWebhookLog`` row, updating its status in place."""
    if raw_webhook.provider is None:
        raw_webhook.status = ProviderWebhookStatus.IGNORED
        raw_webhook.error_message = "No provider associated with this webhook."
        raw_webhook.processed_at = timezone.now()
        raw_webhook.save(update_fields=["status", "error_message", "processed_at"])
        return raw_webhook

    provider_impl = get_provider(raw_webhook.provider)
    parsed = provider_impl.parse_webhook(raw_webhook)

    raw_webhook.error_message = ""

    if parsed.kind == "inbound":
        domain = raw_webhook.domain or provider_impl.resolve_domain(raw_webhook.payload)
        if domain is None:
            raw_webhook.status = ProviderWebhookStatus.IGNORED
            raw_webhook.error_message = (
                "Could not resolve a domain for this inbound message."
            )
        else:
            raw_webhook.domain = domain
            mailbox, recipient_email = resolve_mailbox(domain, parsed.inbound)
            if mailbox is None:
                raw_webhook.status = ProviderWebhookStatus.IGNORED
                raw_webhook.error_message = "No mailbox matched the inbound recipients."
            else:
                try:
                    create_inbound_message(
                        raw_webhook.provider,
                        mailbox,
                        recipient_email,
                        parsed.inbound,
                        raw_webhook,
                    )
                    raw_webhook.status = ProviderWebhookStatus.PROCESSED
                except MailboxQuotaExceeded as exc:
                    raw_webhook.status = ProviderWebhookStatus.IGNORED
                    raw_webhook.error_message = str(exc)
                    logger.error(
                        "Inbound mail dropped: mailbox %s over quota (webhook log %s): %s",
                        mailbox.id,
                        raw_webhook.id,
                        exc,
                    )
    elif parsed.kind == "delivery_event":
        event = create_delivery_event(
            raw_webhook.domain, parsed.delivery_event, raw_webhook
        )
        if event is None:
            raw_webhook.status = ProviderWebhookStatus.IGNORED
            raw_webhook.error_message = (
                "No matching outbound message for this delivery event."
            )
        else:
            raw_webhook.status = ProviderWebhookStatus.PROCESSED
    else:
        raw_webhook.status = ProviderWebhookStatus.IGNORED
        raw_webhook.error_message = f"Unrecognized event type: {parsed.event_type}"

    raw_webhook.processed_at = timezone.now()
    raw_webhook.locked_at = None
    raw_webhook.save(
        update_fields=["status", "domain", "error_message", "processed_at", "locked_at"]
    )
    return raw_webhook
