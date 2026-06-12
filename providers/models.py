from django.db import models
import uuid
from django.utils import timezone
from utils.enums import ProviderType, DomainStatus, ProviderWebhookStatus, EventType


class EmailProvider(models.Model):
    """
    A third-party email service (AWS SES, Postmark, Mailgun, etc.).

    Credentials shape per provider:
      AWS SES    → { "access_key_id": "...", "secret_access_key": "...", "region": "us-east-1" }
      Postmark   → { "server_token": "..." }
      Mailgun    → { "api_key": "...", "base_url": "https://api.mailgun.net" }
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=100, help_text="Human-readable label, e.g. 'AWS SES – US East'"
    )
    provider_type = models.CharField(max_length=30, choices=ProviderType.choices)
    credentials = models.JSONField(
        default=dict,
        help_text="Provider API credentials.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "providers_emailprovider"
        verbose_name = "Email Provider"
        verbose_name_plural = "Email Providers"

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"


class Domain(models.Model):
    """
    A verified sending/receiving domain (e.g., acme.com).
    Each domain is tied to one EmailProvider that handles its outbound delivery.
    Inbound mail arrives via a webhook URL registered with the provider.

    DNS records (SPF, DKIM, DMARC, MX) that the admin must configure are
    stored in `dns_records` so the UI can display them as a checklist.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=253,
        unique=True,
        help_text="Root domain only, e.g. 'acme.com' (no @ or subdomain prefix)",
    )
    provider = models.ForeignKey(
        EmailProvider,
        on_delete=models.PROTECT,
        related_name="domains",
        help_text="Provider responsible for sending/receiving on this domain",
    )
    status = models.CharField(
        max_length=20, choices=DomainStatus, default=DomainStatus.PENDING
    )

    # DNS verification
    verification_token = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="TXT record value used by provider to verify domain ownership",
    )
    dns_records = models.JSONField(
        default=dict,
        help_text=(
            "Required DNS records as returned by the provider. "
            "Example: { 'spf': '...', 'dkim': {...}, 'mx': [...] }"
        ),
    )

    # Inbound routing
    inbound_route = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Inbound webhook route registered with the provider (auto-set on save)",
    )

    # Sending limits (per-domain overrides)
    max_send_per_day = models.PositiveIntegerField(
        default=0,
        help_text="0 = unlimited",
    )

    is_active = models.BooleanField(default=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "domains_domain"
        verbose_name = "Domain"
        verbose_name_plural = "Domains"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def mark_verified(self):
        self.status = "verified"
        self.verified_at = timezone.now()
        self.save(update_fields=["status", "verified_at"])


class DailyDomainSendLog(models.Model):
    """
    Lightweight counter for outbound volume per domain per day.
    Used to enforce Domain.max_send_per_day limits before calling the provider.
    Increment atomically with F() expressions to avoid race conditions.
    """

    domain = models.ForeignKey(
        Domain,
        on_delete=models.CASCADE,
        related_name="daily_send_logs",
    )
    date = models.DateField(db_index=True)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "providers_dailydomainsendlog"
        constraints = [
            models.UniqueConstraint(
                fields=["domain", "date"],
                name="unique_domain_send_day",
            )
        ]

    def __str__(self):
        return f"{self.domain} — {self.date} ({self.sent_count} sent)"


class ProviderWebhookLog(models.Model):
    """
    Raw webhook payloads received from email providers.
    Stored before processing so nothing is lost if a handler crashes.
    A background task (Celery) processes rows where status='pending'.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        EmailProvider,
        on_delete=models.SET_NULL,
        null=True,
        related_name="webhook_logs",
    )
    event_type = models.CharField(
        max_length=100,
        help_text="e.g. 'delivery', 'bounce', 'spam_complaint', 'inbound'",
    )
    payload = models.JSONField(
        default=dict, help_text="Full raw payload from the provider"
    )
    status = models.CharField(
        max_length=15,
        choices=ProviderWebhookStatus.choices,
        default=ProviderWebhookStatus.PENDING,
    )
    error_message = models.TextField(blank=True, null=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "providers_webhooklog"
        verbose_name = "Webhook Log"
        verbose_name_plural = "Webhook Logs"
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["status", "received_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} [{self.status}] @ {self.received_at}"


class DeliveryEvent(models.Model):
    """
    Normalised delivery / bounce / open / click events for outbound messages.
    Populated from ProviderWebhookLog after processing.
    One message can have multiple events (queued → sent → delivered).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        "hedwig.EmailMessage",
        on_delete=models.CASCADE,
        related_name="delivery_events",
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    # For bounces / failures
    reason = models.TextField(blank=True)
    # For click tracking
    link_url = models.URLField(blank=True)
    # Recipient that triggered the event (in multi-recipient sends)
    recipient = models.EmailField(blank=True)
    occurred_at = models.DateTimeField()
    raw_webhook = models.ForeignKey(
        ProviderWebhookLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_events",
    )

    class Meta:
        db_table = "providers_deliveryevent"
        verbose_name = "Delivery Event"
        verbose_name_plural = "Delivery Events"
        ordering = ["occurred_at"]

    def __str__(self):
        return f"{self.message_id} → {self.event_type} @ {self.occurred_at}"
