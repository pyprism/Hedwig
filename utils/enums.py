from django.db import models


class ProviderType(models.TextChoices):
    AWS_SES = "aws_ses", "Amazon SES"
    POSTMARK = "postmark", "Postmark"
    MAILGUN = "mailgun", "Mailgun"
    SENDGRID = "sendgrid", "SendGrid"


class DomainStatus(models.TextChoices):
    PENDING = "pending", "Pending Verification"
    VERIFIED = "verified", "Verified"
    FAILED = "failed", "Verification Failed"
    SUSPENDED = "suspended", "Suspended"


class DnsRecordType(models.TextChoices):
    A = "A", "A"
    CNAME = "CNAME", "CNAME"
    MX = "MX", "MX"
    TXT = "TXT", "TXT"


class DnsRecordStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"
    FAILED = "failed", "Failed"


class AccessType(models.TextChoices):
    MAILBOX = "mailbox", "Mailbox Access"
    DOMAIN = "domain", "Domain Access"


class MailboxPermissionType(models.TextChoices):
    READ_ONLY = "read_only", "Read Only"  # View emails, cannot send
    READ_WRITE = "read_write", "Read & Write"  # View + compose + send
    FULL_ACCESS = "full_access", "Full Access"  # Above + manage mailbox settings


class DirectionType(models.TextChoices):
    INBOUND = "inbound", "Inbound"
    OUTBOUND = "outbound", "Outbound"


class EmailStatus(models.TextChoices):
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    BOUNCED = "bounced", "Bounced"
    OPENED = "opened", "Opened"
    CLICKED = "clicked", "Clicked"
    SPAM = "spam", "Spam"
    DRAFT = "draft", "Draft"
    QUEUED = "queued", "Queued"
    SENDING = "sending", "Sending"
    FAILED = "failed", "Failed"
    RECEIVED = "received", "Received"


class Folder(models.TextChoices):
    INBOX = "inbox", "Inbox"
    SENT = "sent", "Sent"
    DRAFTS = "drafts", "Drafts"
    SPAM = "spam", "Spam"
    ARCHIVE = "archive", "Archive"
    TRASH = "trash", "Trash"


class RecipientType(models.TextChoices):
    TO = "to", "To"
    CC = "cc", "Cc"
    BCC = "bcc", "Bcc"
    REPLY_TO = "reply_to", "Reply-To"


class ProviderWebhookStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"
    IGNORED = "ignored", "Ignored"  # Unrecognised event type


class SendAttemptStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENDING = "sending", "Sending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class EventType(models.TextChoices):
    QUEUED = "queued", "Queued"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    OPENED = "opened", "Opened"
    CLICKED = "clicked", "Clicked"
    BOUNCED = "bounced", "Bounced"
    COMPLAINED = "complained", "Spam Complaint"
    UNSUBSCRIBED = "unsubscribed", "Unsubscribed"
    FAILED = "failed", "Failed"
