import base64
import binascii
import uuid

from django.db import models, transaction
from django.utils import timezone

from utils.enums import (
    AccessType,
    DirectionType,
    EmailStatus,
    Folder,
    RecipientType,
    SendAttemptStatus,
)


def active_access_filter(prefix=""):
    expires_field = f"{prefix}expires_at"
    return models.Q(**{f"{prefix}is_active": True}) & (
        models.Q(**{f"{expires_field}__isnull": True})
        | models.Q(**{f"{expires_field}__gt": timezone.now()})
    )


class MailboxQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def send_enabled(self):
        return self.filter(
            send_enabled=True, is_active=True, domain__outbound_enabled=True
        )

    def receive_enabled(self):
        return self.filter(
            receive_enabled=True, is_active=True, domain__inbound_enabled=True
        )

    def for_api_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_staff or user.is_superuser:
            return self.all()

        mailbox_access = active_access_filter("user_accesses__")
        domain_access = active_access_filter("domain__user_accesses__")
        return self.filter(
            (
                models.Q(user_accesses__user=user)
                & models.Q(user_accesses__access_type=AccessType.MAILBOX)
                & mailbox_access
            )
            | (
                models.Q(domain__user_accesses__user=user)
                & models.Q(domain__user_accesses__access_type=AccessType.DOMAIN)
                & domain_access
            )
        ).distinct()

    def writable_for_user(self, user):
        if user and (user.is_staff or user.is_superuser):
            return self.all()
        return (
            self.for_api_user(user)
            .filter(
                (
                    models.Q(user_accesses__user=user)
                    & models.Q(
                        user_accesses__permission__in=["read_write", "full_access"]
                    )
                    & active_access_filter("user_accesses__")
                )
                | (
                    models.Q(domain__user_accesses__user=user)
                    & models.Q(
                        domain__user_accesses__permission__in=[
                            "read_write",
                            "full_access",
                        ]
                    )
                    & active_access_filter("domain__user_accesses__")
                )
            )
            .distinct()
        )


class MailboxManager(models.Manager.from_queryset(MailboxQuerySet)):
    pass


class MailboxAliasQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_api_user(self, user):
        from hedwig.models import Mailbox

        return self.filter(mailbox__in=Mailbox.objects.for_api_user(user))


class MailboxAliasManager(models.Manager.from_queryset(MailboxAliasQuerySet)):
    pass


class SenderIdentityQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_api_user(self, user):
        from hedwig.models import Mailbox

        return self.filter(mailbox__in=Mailbox.objects.for_api_user(user))


class SenderIdentityManager(models.Manager.from_queryset(SenderIdentityQuerySet)):
    pass


class UserMailboxAccessQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        )

    def for_api_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_staff or user.is_superuser:
            return self.all()
        return self.filter(user=user)


class UserMailboxAccessManager(models.Manager.from_queryset(UserMailboxAccessQuerySet)):
    pass


class EmailThreadQuerySet(models.QuerySet):
    def for_api_user(self, user):
        from hedwig.models import Mailbox

        return self.filter(mailbox__in=Mailbox.objects.for_api_user(user))


class EmailThreadManager(models.Manager.from_queryset(EmailThreadQuerySet)):
    pass


class EmailMessageQuerySet(models.QuerySet):
    def inbound(self):
        return self.filter(direction=DirectionType.INBOUND)

    def outbound(self):
        return self.filter(direction=DirectionType.OUTBOUND)

    def for_api_user(self, user):
        from hedwig.models import Mailbox

        return self.filter(mailbox__in=Mailbox.objects.for_api_user(user))

    def in_folder(self, folder):
        if not folder:
            return self
        return self.filter(folder=folder)


class EmailMessageManager(models.Manager.from_queryset(EmailMessageQuerySet)):
    def create_outbound_message(
        self,
        *,
        mailbox,
        created_by,
        sender_identity=None,
        to_addresses=None,
        cc_addresses=None,
        bcc_addresses=None,
        subject="",
        body_text="",
        body_html="",
        reply_to="",
        metadata=None,
        scheduled_at=None,
        attachments=None,
        thread=None,
        in_reply_to="",
        references="",
    ):
        from hedwig.models import (
            Contact,
            EmailAttachment,
            EmailRecipient,
            OutboundSendAttempt,
        )
        from providers.ingest import update_thread_for_message

        to_addresses = to_addresses or []
        cc_addresses = cc_addresses or []
        bcc_addresses = bcc_addresses or []
        metadata = metadata or {}
        attachments = attachments or []

        sender_email = (
            sender_identity.email if sender_identity else mailbox.email_address
        )
        sender_name = (
            sender_identity.display_name
            if sender_identity and sender_identity.display_name
            else mailbox.display_name
        )
        provider = mailbox.domain.provider
        snippet = (body_text or "").strip().replace("\n", " ")[:500]
        rfc_message_id = f"<{uuid.uuid4()}@{mailbox.domain.name}>"

        with transaction.atomic():
            message = self.create(
                mailbox=mailbox,
                thread=thread,
                sender_identity=sender_identity,
                created_by=created_by,
                direction=DirectionType.OUTBOUND,
                status=EmailStatus.QUEUED,
                folder=Folder.SENT,
                rfc_message_id=rfc_message_id,
                from_address=sender_email,
                from_name=sender_name,
                to_addresses=to_addresses,
                cc_addresses=cc_addresses,
                bcc_addresses=bcc_addresses,
                reply_to=reply_to,
                subject=subject,
                in_reply_to=in_reply_to,
                references=references,
                body_text=body_text,
                body_html=body_html,
                snippet=snippet,
                provider=provider,
                is_read=True,
                metadata=metadata,
                scheduled_at=scheduled_at,
            )
            update_thread_for_message(mailbox, message)
            for recipient_type, rows in (
                (RecipientType.TO, to_addresses),
                (RecipientType.CC, cc_addresses),
                (RecipientType.BCC, bcc_addresses),
            ):
                EmailRecipient.objects.bulk_create(
                    [
                        EmailRecipient(
                            message=message,
                            recipient_type=recipient_type,
                            email=row["email"],
                            name=row.get("name", ""),
                        )
                        for row in rows
                    ]
                )
            for row in to_addresses + cc_addresses + bcc_addresses:
                Contact.objects.record_contact(
                    mailbox, row["email"], row.get("name", "")
                )
            if attachments:
                total_size = 0
                for attachment in attachments:
                    filename = attachment.get("filename") or "attachment"
                    content_type = (
                        attachment.get("content_type") or "application/octet-stream"
                    )
                    content_b64 = attachment.get("content")
                    try:
                        size_bytes = (
                            len(base64.b64decode(content_b64)) if content_b64 else 0
                        )
                    except (binascii.Error, ValueError):
                        size_bytes = 0
                    total_size += size_bytes
                    EmailAttachment.objects.create(
                        message=message,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=size_bytes,
                        content_id=attachment.get("content_id") or None,
                        is_inline=bool(attachment.get("content_id")),
                        metadata={
                            "source": "outbound_compose",
                            "pending_content_b64": content_b64,
                        },
                    )
                message.has_attachments = True
                message.size_bytes = total_size
                message.save(
                    update_fields=["has_attachments", "size_bytes", "updated_at"]
                )
            attempt = OutboundSendAttempt.objects.create(
                message=message,
                provider=provider,
                attempt_number=1,
                status=SendAttemptStatus.PENDING,
                idempotency_key=uuid.uuid4().hex[:16],
                request_payload={},
            )
        return message, attempt


class EmailRecipientQuerySet(models.QuerySet):
    def for_api_user(self, user):
        from hedwig.models import EmailMessage

        return self.filter(message__in=EmailMessage.objects.for_api_user(user))


class EmailRecipientManager(models.Manager.from_queryset(EmailRecipientQuerySet)):
    pass


class EmailMessageUserStateQuerySet(models.QuerySet):
    def for_api_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_staff or user.is_superuser:
            return self.all()
        return self.filter(user=user)


class EmailMessageUserStateManager(
    models.Manager.from_queryset(EmailMessageUserStateQuerySet)
):
    pass


class OutboundSendAttemptQuerySet(models.QuerySet):
    def for_api_user(self, user):
        from hedwig.models import EmailMessage

        return self.filter(message__in=EmailMessage.objects.for_api_user(user))


class OutboundSendAttemptManager(
    models.Manager.from_queryset(OutboundSendAttemptQuerySet)
):
    pass


class EmailAttachmentQuerySet(models.QuerySet):
    def for_api_user(self, user):
        from hedwig.models import EmailMessage

        return self.filter(message__in=EmailMessage.objects.for_api_user(user))


class EmailAttachmentManager(models.Manager.from_queryset(EmailAttachmentQuerySet)):
    pass


class EmailLabelQuerySet(models.QuerySet):
    def for_api_user(self, user):
        from hedwig.models import Mailbox

        return self.filter(mailbox__in=Mailbox.objects.for_api_user(user))


class EmailLabelManager(models.Manager.from_queryset(EmailLabelQuerySet)):
    pass


class EmailMessageLabelQuerySet(models.QuerySet):
    def for_api_user(self, user):
        from hedwig.models import EmailMessage

        return self.filter(message__in=EmailMessage.objects.for_api_user(user))


class EmailMessageLabelManager(models.Manager.from_queryset(EmailMessageLabelQuerySet)):
    pass


class MailboxRuleQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_api_user(self, user):
        from hedwig.models import Mailbox

        return self.filter(mailbox__in=Mailbox.objects.for_api_user(user))


class MailboxRuleManager(models.Manager.from_queryset(MailboxRuleQuerySet)):
    pass


class SuppressedAddressQuerySet(models.QuerySet):
    def for_api_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_staff or user.is_superuser:
            return self.all()
        from hedwig.models import Mailbox
        from providers.models import Domain

        return self.filter(
            models.Q(mailbox__in=Mailbox.objects.for_api_user(user))
            | models.Q(
                domain__in=Domain.objects.for_api_user(user), mailbox__isnull=True
            )
        ).distinct()

    def active(self):
        now = timezone.now()
        return self.filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )

    def suppressed_emails(self, mailbox, emails):
        """Return the subset of ``emails`` suppressed for ``mailbox`` (mailbox- or domain-wide)."""
        emails = {email.strip().lower() for email in emails if email}
        if not emails:
            return set()
        return set(
            self.active()
            .filter(
                models.Q(domain_id=mailbox.domain_id, mailbox__isnull=True)
                | models.Q(mailbox=mailbox),
                email__in=emails,
            )
            .values_list("email", flat=True)
        )


class SuppressedAddressManager(models.Manager.from_queryset(SuppressedAddressQuerySet)):
    pass


class ContactQuerySet(models.QuerySet):
    def for_api_user(self, user):
        from hedwig.models import Mailbox

        return self.filter(mailbox__in=Mailbox.objects.for_api_user(user))


class ContactManager(models.Manager.from_queryset(ContactQuerySet)):
    def record_contact(self, mailbox, email, name=""):
        email = (email or "").strip().lower()
        if not email:
            return None

        contact, created = self.get_or_create(
            mailbox=mailbox,
            email=email,
            defaults={
                "name": name,
                "times_contacted": 1,
                "last_contacted_at": timezone.now(),
            },
        )
        if not created:
            update_fields = ["times_contacted", "last_contacted_at"]
            contact.times_contacted = models.F("times_contacted") + 1
            contact.last_contacted_at = timezone.now()
            if name and not contact.name:
                contact.name = name
                update_fields.append("name")
            contact.save(update_fields=update_fields)
        return contact
