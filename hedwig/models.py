from django.db import models
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from utils.enums import (
    AccessType,
    DirectionType,
    EmailStatus,
    Folder,
    MailboxPermissionType,
    RecipientType,
    SendAttemptStatus,
)


local_part_validator = RegexValidator(
    regex=r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$",
    message="Use only a valid email local-part, without the @domain.",
)


class Mailbox(models.Model):
    """
    A single email address / inbox (e.g., john@acme.com).
    `local_part` + domain.name = the full email address.

    Admin creates mailboxes and then assigns them to users via
    UserMailboxAccess. One mailbox can be shared by multiple users.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.ForeignKey(
        "providers.Domain",
        on_delete=models.CASCADE,
        related_name="mailboxes",
    )
    local_part = models.CharField(
        max_length=64,
        validators=[local_part_validator],
        help_text="Part before the @. E.g. 'john' for john@acme.com",
    )
    display_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Friendly sender name shown in email clients",
    )
    # Forwarding / catch-all
    is_catch_all = models.BooleanField(
        default=False,
        help_text="Receives mail sent to any unmatched address on this domain",
    )
    forward_to = models.EmailField(
        blank=True,
        help_text="If set, incoming mail is also forwarded to this external address",
    )
    reply_to = models.EmailField(blank=True)
    send_enabled = models.BooleanField(default=True)
    receive_enabled = models.BooleanField(default=True)
    quota_bytes = models.BigIntegerField(
        default=0,
        help_text="0 = unlimited. Enforce while storing inbound mail and attachments.",
    )
    used_bytes = models.BigIntegerField(default=0)
    signature_html = models.TextField(blank=True)
    signature_text = models.TextField(blank=True)
    provider_sender_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Provider-side sender or stream identifier if applicable.",
    )
    metadata = models.JSONField(default=dict, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mailboxes_mailbox"
        verbose_name = "Mailbox"
        verbose_name_plural = "Mailboxes"
        # Enforce uniqueness of the full address within a domain
        constraints = [
            models.UniqueConstraint(
                Lower("local_part"),
                "domain",
                name="unique_mailbox_per_domain",
            )
        ]
        indexes = [
            models.Index(fields=["domain", "is_active"]),
            models.Index(fields=["domain", "is_catch_all"]),
        ]

    def __str__(self):
        return self.email_address

    @property
    def email_address(self) -> str:
        return f"{self.local_part}@{self.domain.name}"

    def clean(self):
        super().clean()
        if self.local_part:
            self.local_part = self.local_part.strip().lower()


class MailboxAlias(models.Model):
    """
    Additional address on the same domain that delivers into a mailbox.
    Example: support@acme.com can deliver into jane@acme.com.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mailbox = models.ForeignKey(
        Mailbox,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    domain = models.ForeignKey(
        "providers.Domain",
        on_delete=models.CASCADE,
        related_name="mailbox_aliases",
    )
    local_part = models.CharField(max_length=64, validators=[local_part_validator])
    display_name = models.CharField(max_length=150, blank=True)
    can_send = models.BooleanField(default=True)
    can_receive = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mailboxes_alias"
        verbose_name = "Mailbox Alias"
        verbose_name_plural = "Mailbox Aliases"
        ordering = ["domain__name", "local_part"]
        constraints = [
            models.UniqueConstraint(
                Lower("local_part"),
                "domain",
                name="unique_alias_per_domain",
            )
        ]
        indexes = [
            models.Index(fields=["domain", "is_active"]),
            models.Index(fields=["mailbox", "is_active"]),
        ]

    def __str__(self):
        return self.email_address

    @property
    def email_address(self) -> str:
        return f"{self.local_part}@{self.domain.name}"

    def clean(self):
        super().clean()
        if self.local_part:
            self.local_part = self.local_part.strip().lower()
        if (
            self.mailbox_id
            and self.domain_id
            and self.mailbox.domain_id != self.domain_id
        ):
            raise ValidationError("Alias domain must match the mailbox domain.")
        if (
            self.domain_id
            and self.local_part
            and Mailbox.objects.filter(
                domain_id=self.domain_id,
                local_part__iexact=self.local_part,
            ).exists()
        ):
            raise ValidationError("Alias conflicts with an existing mailbox address.")


class SenderIdentity(models.Model):
    """
    A selectable From identity for composing mail from a mailbox or alias.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mailbox = models.ForeignKey(
        Mailbox,
        on_delete=models.CASCADE,
        related_name="sender_identities",
    )
    alias = models.ForeignKey(
        MailboxAlias,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sender_identities",
    )
    email = models.EmailField()
    display_name = models.CharField(max_length=150, blank=True)
    reply_to = models.EmailField(blank=True)
    signature_html = models.TextField(blank=True)
    signature_text = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mailboxes_senderidentity"
        verbose_name = "Sender Identity"
        verbose_name_plural = "Sender Identities"
        ordering = ["mailbox__local_part", "email"]
        constraints = [
            models.UniqueConstraint(
                "mailbox",
                Lower("email"),
                name="unique_sender_identity_per_mailbox",
            ),
            models.UniqueConstraint(
                fields=["mailbox"],
                condition=Q(is_default=True),
                name="unique_default_sender_identity_per_mailbox",
            ),
        ]
        indexes = [
            models.Index(fields=["mailbox", "is_active"]),
        ]

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        self.email = self.email.strip().lower()
        if self.alias_id and self.alias.mailbox_id != self.mailbox_id:
            raise ValidationError("Sender identity alias must belong to the mailbox.")


class UserMailboxAccess(models.Model):
    """
    Grants a user access to either:
      - A specific mailbox  (access_type = 'mailbox')
      - All mailboxes on a domain  (access_type = 'domain')

    Only one of `mailbox` or `domain` should be set, matching `access_type`.
    A CHECK constraint enforces this at the DB level.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="mailbox_accesses",
    )
    access_type = models.CharField(max_length=10, choices=AccessType.choices)
    # Set exactly ONE of these two fields based on access_type
    mailbox = models.ForeignKey(
        Mailbox,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_accesses",
    )
    domain = models.ForeignKey(
        "providers.Domain",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_accesses",
    )
    permission = models.CharField(
        max_length=15,
        choices=MailboxPermissionType.choices,
        default=MailboxPermissionType.READ_WRITE,
    )
    granted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="granted_accesses",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional. Access auto-expires after this datetime.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "mailboxes_usermailboxaccess"
        verbose_name = "User Mailbox Access"
        verbose_name_plural = "User Mailbox Accesses"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        access_type=AccessType.MAILBOX,
                        mailbox__isnull=False,
                        domain__isnull=True,
                    )
                    | Q(
                        access_type=AccessType.DOMAIN,
                        mailbox__isnull=True,
                        domain__isnull=False,
                    )
                ),
                name="access_target_matches_type",
            ),
            # Prevent duplicate grants for the same (user, mailbox) pair
            models.UniqueConstraint(
                fields=["user", "mailbox"],
                condition=Q(access_type=AccessType.MAILBOX, is_active=True),
                name="unique_user_mailbox_access",
            ),
            # Prevent duplicate grants for the same (user, domain) pair
            models.UniqueConstraint(
                fields=["user", "domain"],
                condition=Q(access_type=AccessType.DOMAIN, is_active=True),
                name="unique_user_domain_access",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "access_type", "is_active"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        target = self.mailbox or self.domain
        return f"{self.user.username} → {target} ({self.get_permission_display()})"

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at

    def clean(self):
        super().clean()
        if self.access_type == AccessType.MAILBOX and (
            self.mailbox_id is None or self.domain_id is not None
        ):
            raise ValidationError("Mailbox access must target exactly one mailbox.")
        if self.access_type == AccessType.DOMAIN and (
            self.domain_id is None or self.mailbox_id is not None
        ):
            raise ValidationError("Domain access must target exactly one domain.")


class EmailThread(models.Model):
    """
    Groups related messages (a conversation chain) together.
    The thread_id is derived from the first message's Message-ID header,
    similar to how Gmail threads conversations.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mailbox = models.ForeignKey(
        Mailbox,
        on_delete=models.CASCADE,
        related_name="threads",
    )
    subject = models.CharField(max_length=998, blank=True, null=True)
    normalized_subject = models.CharField(max_length=998, blank=True)
    root_message_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="Message-ID that started the conversation, when known.",
    )
    # Participants (union of all from/to/cc addresses in the thread)
    participants = models.JSONField(default=list)
    message_count = models.PositiveIntegerField(default=0)
    has_unread = models.BooleanField(default=True, db_index=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "emails_thread"
        verbose_name = "Email Thread"
        verbose_name_plural = "Email Threads"
        ordering = ["-last_message_at"]
        indexes = [
            models.Index(fields=["mailbox", "-last_message_at"]),
            models.Index(fields=["mailbox", "has_unread"]),
        ]

    def __str__(self):
        return f"Thread: {self.subject or '(no subject)'}"


class EmailMessage(models.Model):
    """
    A single email message — inbound or outbound.

    Direction:
      inbound  → received via provider webhook
      outbound → composed by the user and sent via provider API

    The `raw_headers` JSON preserves all MIME headers for compliance / debugging.
    Threading is done via `thread` FK and `in_reply_to` / `references` headers.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mailbox = models.ForeignKey(
        Mailbox,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    thread = models.ForeignKey(
        EmailThread,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    sender_identity = models.ForeignKey(
        SenderIdentity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
        help_text="Identity selected for outbound mail.",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_messages",
    )

    direction = models.CharField(
        max_length=10, choices=DirectionType.choices, db_index=True
    )
    status = models.CharField(
        max_length=15, choices=EmailStatus.choices, default=EmailStatus.RECEIVED
    )
    folder = models.CharField(
        max_length=10, choices=Folder.choices, default=Folder.INBOX, db_index=True
    )

    #  RFC 2822 Headers
    # Unique Message-ID from the email headers (e.g. <abc@mail.example.com>)
    rfc_message_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="Value of the Message-ID header (RFC 2822)",
    )
    from_address = models.EmailField()
    from_name = models.CharField(max_length=255, blank=True, null=True)
    envelope_sender = models.EmailField(
        blank=True,
        help_text="SMTP MAIL FROM / return-path address.",
    )
    envelope_recipient = models.EmailField(
        blank=True,
        help_text="SMTP RCPT TO that caused delivery to this mailbox.",
    )
    to_addresses = models.JSONField(
        default=list,
        help_text='List of dicts: [{"email": "...", "name": "..."}]',
    )
    cc_addresses = models.JSONField(default=list)
    bcc_addresses = models.JSONField(default=list)
    reply_to = models.EmailField(blank=True)
    subject = models.CharField(max_length=998, blank=True)

    # Threading headers
    in_reply_to = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="RFC 2822 In-Reply-To header value",
    )
    references = models.TextField(
        blank=True,
        null=True,
        help_text="Space-separated list of referenced Message-IDs",
    )

    #  Body
    body_text = models.TextField(blank=True, help_text="Plain-text part")
    body_html = models.TextField(blank=True, help_text="HTML part")
    snippet = models.CharField(max_length=500, blank=True)
    raw_headers = models.JSONField(
        default=dict,
        help_text="All raw MIME headers preserved for debugging / compliance",
    )
    raw_mime_url = models.URLField(
        blank=True,
        help_text="Object-storage URL for the raw MIME source, if retained.",
    )

    # Provider Tracking
    provider = models.ForeignKey(
        "providers.EmailProvider",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
        help_text="Provider that sent or received this message",
    )
    provider_message_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Provider-assigned ID (for delivery tracking / webhooks)",
    )

    # Metadata
    is_read = models.BooleanField(default=False, db_index=True)
    is_starred = models.BooleanField(default=False)
    has_attachments = models.BooleanField(default=False)
    size_bytes = models.PositiveIntegerField(default=0)
    spam_score = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    metadata = models.JSONField(default=dict, blank=True)

    # Timestamps
    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "emails_message"
        verbose_name = "Email Message"
        verbose_name_plural = "Email Messages"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["mailbox", "folder", "-created_at"]),
            models.Index(fields=["mailbox", "is_read"]),
            models.Index(fields=["thread", "-created_at"]),
            models.Index(fields=["direction", "status"]),
            models.Index(fields=["provider_message_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["mailbox", "rfc_message_id"],
                condition=Q(rfc_message_id__isnull=False),
                name="unique_rfc_message_per_mailbox",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_message_id"],
                condition=~Q(provider_message_id="")
                & Q(provider_message_id__isnull=False),
                name="unique_provider_message_id",
            ),
        ]

    def __str__(self):
        return f"[{self.direction.upper()}] {self.subject or '(no subject)'}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=["is_read"])


class EmailRecipient(models.Model):
    """
    Searchable recipient rows for an EmailMessage.
    JSON address lists remain on EmailMessage for preserving provider payload shape.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        EmailMessage,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    recipient_type = models.CharField(max_length=10, choices=RecipientType.choices)
    email = models.EmailField()
    name = models.CharField(max_length=255, blank=True)
    delivered_to_mailbox = models.ForeignKey(
        Mailbox,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivered_recipient_rows",
        help_text="Mailbox this recipient mapped to for inbound delivery.",
    )
    provider_recipient_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=15,
        choices=EmailStatus.choices,
        default=EmailStatus.QUEUED,
        db_index=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "emails_recipient"
        verbose_name = "Email Recipient"
        verbose_name_plural = "Email Recipients"
        ordering = ["recipient_type", "email"]
        indexes = [
            models.Index(fields=["message", "recipient_type"]),
            models.Index(fields=["email", "status"]),
        ]

    def __str__(self):
        return f"{self.get_recipient_type_display()}: {self.email}"

    def clean(self):
        super().clean()
        if self.email:
            self.email = self.email.strip().lower()


class EmailMessageUserState(models.Model):
    """
    Per-user mailbox state for shared inboxes.
    This lets two users share a mailbox while keeping read/starred/folder state
    independent where the product wants that behavior.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="message_states",
    )
    message = models.ForeignKey(
        EmailMessage,
        on_delete=models.CASCADE,
        related_name="user_states",
    )
    folder = models.CharField(
        max_length=10,
        choices=Folder.choices,
        default=Folder.INBOX,
        db_index=True,
    )
    is_read = models.BooleanField(default=False, db_index=True)
    is_starred = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "emails_messageuserstate"
        verbose_name = "Email Message User State"
        verbose_name_plural = "Email Message User States"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "message"],
                name="unique_user_message_state",
            )
        ]
        indexes = [
            models.Index(fields=["user", "folder", "-updated_at"]),
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["snoozed_until"]),
        ]

    def __str__(self):
        return f"{self.user_id} / {self.message_id}"


class OutboundSendAttempt(models.Model):
    """
    Auditable provider send attempt.
    Create a new row for every provider API call so retries are explainable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        EmailMessage,
        on_delete=models.CASCADE,
        related_name="send_attempts",
    )
    provider = models.ForeignKey(
        "providers.EmailProvider",
        on_delete=models.PROTECT,
        related_name="send_attempts",
    )
    attempt_number = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=15,
        choices=SendAttemptStatus.choices,
        default=SendAttemptStatus.PENDING,
        db_index=True,
    )
    provider_message_id = models.CharField(max_length=255, blank=True)
    idempotency_key = models.CharField(max_length=255, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "emails_outboundsendattempt"
        verbose_name = "Outbound Send Attempt"
        verbose_name_plural = "Outbound Send Attempts"
        ordering = ["message_id", "attempt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["message", "attempt_number"],
                name="unique_send_attempt_number",
            ),
            models.UniqueConstraint(
                fields=["provider", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="unique_provider_send_idempotency_key",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "status", "created_at"]),
            models.Index(fields=["provider_message_id"]),
        ]

    def __str__(self):
        return f"{self.message_id} attempt {self.attempt_number} [{self.status}]"


class EmailAttachment(models.Model):
    """
    File attached to an EmailMessage.
    `content_id` is set for inline (embedded) images; `is_inline` flags them.
    Files are stored in object storage S3.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        EmailMessage,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    filename = models.CharField(max_length=255)
    content_type = models.CharField(
        max_length=100, help_text="MIME type, e.g. image/png"
    )
    size_bytes = models.PositiveIntegerField()
    file = models.URLField()
    storage_key = models.CharField(
        max_length=1024,
        blank=True,
        help_text="Object storage key/path for provider-independent access.",
    )
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    # For inline images referenced in HTML body via cid:
    content_id = models.CharField(max_length=255, blank=True, null=True)
    content_disposition = models.CharField(max_length=100, blank=True)
    is_inline = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "emails_attachment"
        verbose_name = "Email Attachment"
        verbose_name_plural = "Email Attachments"
        indexes = [
            models.Index(fields=["message", "is_inline"]),
            models.Index(fields=["checksum_sha256"]),
        ]

    def __str__(self):
        return self.filename


class EmailLabel(models.Model):
    """
    User-defined color labels (similar to Gmail labels) scoped per mailbox.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mailbox = models.ForeignKey(
        Mailbox,
        on_delete=models.CASCADE,
        related_name="labels",
    )
    name = models.CharField(max_length=50)
    color = models.CharField(
        max_length=7, default="#3B82F6", help_text="Hex color code"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "emails_label"
        verbose_name = "Email Label"
        verbose_name_plural = "Email Labels"
        constraints = [
            models.UniqueConstraint(
                fields=["mailbox", "name"],
                name="unique_label_per_mailbox",
            )
        ]

    def __str__(self):
        return f"{self.mailbox} / {self.name}"


class EmailMessageLabel(models.Model):
    """
    Many-to-many: EmailMessage ↔ EmailLabel.
    Separated from EmailMessage to allow bulk labelling without locking the message row.
    """

    message = models.ForeignKey(
        EmailMessage,
        on_delete=models.CASCADE,
        related_name="message_labels",
    )
    label = models.ForeignKey(
        EmailLabel,
        on_delete=models.CASCADE,
        related_name="message_labels",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "emails_messagelabel"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "label"],
                name="unique_message_label",
            )
        ]


class MailboxRule(models.Model):
    """
    User/admin-defined filter rule for inbound messages.
    Conditions and actions are JSON so the rule engine can evolve without
    schema churn during early product development.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mailbox = models.ForeignKey(
        Mailbox,
        on_delete=models.CASCADE,
        related_name="rules",
    )
    name = models.CharField(max_length=150)
    priority = models.PositiveSmallIntegerField(default=100)
    conditions = models.JSONField(
        default=dict,
        help_text="Rule predicates, e.g. from_contains, subject_contains, has_attachment.",
    )
    actions = models.JSONField(
        default=dict,
        help_text="Rule actions, e.g. add_label, move_to_folder, forward_to.",
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mailbox_rules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mailboxes_rule"
        verbose_name = "Mailbox Rule"
        verbose_name_plural = "Mailbox Rules"
        ordering = ["mailbox", "priority", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["mailbox", "name"],
                name="unique_rule_name_per_mailbox",
            )
        ]
        indexes = [
            models.Index(fields=["mailbox", "is_active", "priority"]),
        ]

    def __str__(self):
        return f"{self.mailbox} / {self.name}"


class SuppressedAddress(models.Model):
    """
    Addresses that should not receive outbound mail from a mailbox/domain.
    Can be populated from unsubscribe, bounce, complaint, or admin action.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.ForeignKey(
        "providers.Domain",
        on_delete=models.CASCADE,
        related_name="suppressed_addresses",
    )
    mailbox = models.ForeignKey(
        Mailbox,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="suppressed_addresses",
        help_text="Blank means the suppression applies to the whole domain.",
    )
    email = models.EmailField()
    reason = models.CharField(max_length=100, blank=True)
    source = models.CharField(
        max_length=100,
        blank=True,
        help_text="unsubscribe, bounce, complaint, admin, import, etc.",
    )
    raw_event = models.ForeignKey(
        "providers.ProviderWebhookLog",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suppressed_addresses",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "emails_suppressedaddress"
        verbose_name = "Suppressed Address"
        verbose_name_plural = "Suppressed Addresses"
        constraints = [
            models.UniqueConstraint(
                "domain",
                Lower("email"),
                condition=Q(mailbox__isnull=True),
                name="unique_domain_suppressed_address",
            ),
            models.UniqueConstraint(
                "domain",
                "mailbox",
                Lower("email"),
                condition=Q(mailbox__isnull=False),
                name="unique_mailbox_suppressed_address",
            ),
        ]
        indexes = [
            models.Index(fields=["domain", "email"]),
            models.Index(fields=["mailbox", "email"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        scope = self.mailbox or self.domain
        return f"{self.email} suppressed for {scope}"

    def clean(self):
        super().clean()
        if self.email:
            self.email = self.email.strip().lower()
        if (
            self.mailbox_id
            and self.domain_id
            and self.mailbox.domain_id != self.domain_id
        ):
            raise ValidationError("Suppression domain must match the mailbox domain.")
