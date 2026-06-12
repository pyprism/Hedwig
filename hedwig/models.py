from django.db import models
import uuid

from django.utils import timezone

from utils.enums import (
    AccessType,
    MailboxPermissionType,
    DirectionType,
    EmailStatus,
    Folder,
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
        null=True,
        help_text="If set, incoming mail is also forwarded to this external address",
    )

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
                fields=["domain", "local_part"],
                name="unique_mailbox_per_domain",
            )
        ]

    def __str__(self):
        return self.email_address

    @property
    def email_address(self) -> str:
        return f"{self.local_part}@{self.domain.name}"


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

    class Meta:
        db_table = "mailboxes_usermailboxaccess"
        verbose_name = "User Mailbox Access"
        verbose_name_plural = "User Mailbox Accesses"
        constraints = [
            # Prevent duplicate grants for the same (user, mailbox) pair
            models.UniqueConstraint(
                fields=["user", "mailbox"],
                condition=models.Q(access_type="mailbox"),
                name="unique_user_mailbox_access",
            ),
            # Prevent duplicate grants for the same (user, domain) pair
            models.UniqueConstraint(
                fields=["user", "domain"],
                condition=models.Q(access_type="domain"),
                name="unique_user_domain_access",
            ),
        ]

    def __str__(self):
        target = self.mailbox or self.domain
        return f"{self.user.username} → {target} ({self.get_permission_display()})"

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at


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
    raw_headers = models.JSONField(
        default=dict,
        help_text="All raw MIME headers preserved for debugging / compliance",
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

    # Timestamps
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
            models.Index(fields=["provider_message_id"]),
        ]

    def __str__(self):
        return f"[{self.direction.upper()}] {self.subject or '(no subject)'}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=["is_read"])


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
    # For inline images referenced in HTML body via cid:
    content_id = models.CharField(max_length=255, blank=True, null=True)
    is_inline = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "emails_attachment"
        verbose_name = "Email Attachment"
        verbose_name_plural = "Email Attachments"

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
