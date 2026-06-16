"""Mailbox rule evaluation and inbound forwarding.

``MailboxRule.conditions``/``actions`` are evaluated in priority order during
inbound ingestion (see ``providers.ingest.create_inbound_message``).
"""

from django.db import transaction


SUPPORTED_CONDITIONS = {
    "from_contains",
    "subject_contains",
    "to_contains",
    "cc_contains",
    "has_attachment",
    "has_label",
}
SUPPORTED_ACTIONS = {
    "add_label",
    "move_to_folder",
    "forward_to",
    "stop",
    "continue",
}


def _rows_contain(rows, value):
    needle = (value or "").lower()
    return any(needle in (row.get("email") or "").lower() for row in rows or [])


def _rule_matches(conditions, message):
    if not conditions:
        return False

    from_contains = conditions.get("from_contains")
    if (
        from_contains
        and from_contains.lower() not in (message.from_address or "").lower()
    ):
        return False

    subject_contains = conditions.get("subject_contains")
    if (
        subject_contains
        and subject_contains.lower() not in (message.subject or "").lower()
    ):
        return False

    to_contains = conditions.get("to_contains")
    if to_contains and not _rows_contain(message.to_addresses, to_contains):
        return False

    cc_contains = conditions.get("cc_contains")
    if cc_contains and not _rows_contain(message.cc_addresses, cc_contains):
        return False

    has_attachment = conditions.get("has_attachment")
    if has_attachment is not None and bool(has_attachment) != message.has_attachments:
        return False

    has_label = conditions.get("has_label")
    if has_label:
        if not message.message_labels.filter(label__name=has_label).exists():
            return False

    return True


def _apply_actions(mailbox, message, actions):
    from hedwig.models import EmailLabel, EmailMessageLabel

    label_name = actions.get("add_label")
    if label_name:
        label, _ = EmailLabel.objects.get_or_create(mailbox=mailbox, name=label_name)
        EmailMessageLabel.objects.get_or_create(message=message, label=label)

    folder = actions.get("move_to_folder")
    if folder and folder != message.folder:
        message.folder = folder
        message.save(update_fields=["folder", "updated_at"])

    forward_to = actions.get("forward_to")
    if forward_to:
        forward_message(message, forward_to, reason="rule")

    return bool(actions.get("stop")) or actions.get("continue") is False


def evaluate_rules(mailbox, message):
    """Run ``mailbox``'s active rules against ``message`` in priority order."""
    from hedwig.models import MailboxRule

    rules = (
        MailboxRule.objects.active()
        .filter(mailbox=mailbox)
        .order_by("priority", "name")
    )
    for rule in rules:
        if _rule_matches(rule.conditions or {}, message):
            should_stop = _apply_actions(mailbox, message, rule.actions or {})
            if should_stop:
                break


def forward_message(message, to_email, reason="forward"):
    """Forward an inbound ``message`` to ``to_email`` as a new outbound message."""
    from hedwig.models import EmailMessage
    from hedwig.tasks import send_email_message_task

    mailbox = message.mailbox
    sender_identity = mailbox.sender_identities.filter(
        is_default=True, is_active=True
    ).first()

    subject = message.subject or ""
    if not subject.lower().startswith("fwd:"):
        subject = f"Fwd: {subject}".strip()

    forwarded_header = (
        "---------- Forwarded message ----------\n"
        f"From: {message.from_name or ''} <{message.from_address}>\n"
        f"Subject: {message.subject or ''}\n\n"
    )

    new_message, attempt = EmailMessage.objects.create_outbound_message(
        mailbox=mailbox,
        created_by=None,
        sender_identity=sender_identity,
        to_addresses=[{"email": to_email, "name": ""}],
        subject=subject,
        body_text=forwarded_header + (message.body_text or ""),
        body_html=message.body_html or "",
        metadata={"forwarded_from": str(message.id), "forward_reason": reason},
    )
    if message.has_attachments:
        _copy_attachments(message, new_message)
    transaction.on_commit(
        lambda: send_email_message_task.delay(str(new_message.id), str(attempt.id))
    )
    return new_message


def _copy_attachments(source_message, target_message):
    """Re-attach ``source_message``'s stored attachments to ``target_message``.

    Reuses the same S3 objects (file/storage_key) rather than re-uploading.
    """
    from hedwig.models import EmailAttachment

    total_size = target_message.size_bytes
    copied = False
    for attachment in source_message.attachments.all():
        EmailAttachment.objects.create(
            message=target_message,
            filename=attachment.filename,
            content_type=attachment.content_type,
            size_bytes=attachment.size_bytes,
            file=attachment.file,
            storage_key=attachment.storage_key,
            checksum_sha256=attachment.checksum_sha256,
            content_id=attachment.content_id,
            content_disposition=attachment.content_disposition,
            is_inline=attachment.is_inline,
        )
        total_size += attachment.size_bytes
        copied = True

    if copied:
        target_message.has_attachments = True
        target_message.size_bytes = total_size
        target_message.save(
            update_fields=["has_attachments", "size_bytes", "updated_at"]
        )
