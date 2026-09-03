import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import models
from django.utils import timezone

from providers.catch_all_coverage import find_domains_missing_catch_all
from providers.ingest import process_webhook_log
from providers.models import (
    DailyDomainSendLog,
    Domain,
    EmailProvider,
    ProviderWebhookLog,
)
from providers.registry import get_provider
from utils.enums import DomainStatus, ProviderWebhookStatus

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = {
    ProviderWebhookStatus.PENDING,
    ProviderWebhookStatus.PROCESSING,
    ProviderWebhookStatus.FAILED,
}


@shared_task(bind=True, max_retries=5)
def process_webhook_log_task(self, webhook_log_id):
    """Worker-side processing for a webhook persisted by the fast-path webhook view.

    Uses ``locked_at``/``attempt_count`` so a row already marked processed/ignored by
    a previous delivery of this task is not reprocessed.
    """
    # Claim the row with a single conditional UPDATE instead of a plain
    # read-then-save: a WHERE ... UPDATE is atomic at the row level, so two
    # concurrent deliveries of this task for the same webhook_log_id (e.g. a
    # broker redelivery landing alongside the stale-retry sweep) can't both
    # read "retryable" and both proceed to process it — only the first UPDATE
    # actually matches and flips the row.
    #
    # A row already PROCESSING is only reclaimable if its lock has gone
    # stale (same threshold retry_stale_webhook_logs_task uses to decide a
    # row is worth re-dispatching) — otherwise a merely-slow-but-still-alive
    # task (e.g. a large attachment upload) would get double-processed by a
    # second delivery that finds status==PROCESSING and, before this check
    # existed, reclaimed it anyway just because PROCESSING was unconditionally
    # in RETRYABLE_STATUSES.
    stale_before = timezone.now() - timedelta(
        minutes=settings.WEBHOOK_LOG_RETRY_STALE_MINUTES
    )
    claimed = (
        ProviderWebhookLog.objects.filter(pk=webhook_log_id)
        .filter(
            models.Q(
                status__in={ProviderWebhookStatus.PENDING, ProviderWebhookStatus.FAILED}
            )
            | models.Q(
                status=ProviderWebhookStatus.PROCESSING,
                locked_at__lt=stale_before,
            )
        )
        .update(
            status=ProviderWebhookStatus.PROCESSING,
            locked_at=timezone.now(),
            attempt_count=models.F("attempt_count") + 1,
        )
    )
    if not claimed:
        raw_webhook = ProviderWebhookLog.objects.filter(pk=webhook_log_id).first()
        if raw_webhook is None:
            return {"status": "missing", "id": str(webhook_log_id)}
        return {"status": raw_webhook.status, "id": str(webhook_log_id)}

    raw_webhook = ProviderWebhookLog.objects.select_related("provider", "domain").get(
        pk=webhook_log_id
    )

    try:
        raw_webhook = process_webhook_log(raw_webhook)
    except Exception as exc:
        raw_webhook.status = ProviderWebhookStatus.FAILED
        raw_webhook.error_message = str(exc)
        raw_webhook.save(update_fields=["status", "error_message"])
        raise self.retry(
            exc=exc, countdown=min(60 * 2**raw_webhook.attempt_count, 3600)
        )

    return {"status": raw_webhook.status, "id": str(webhook_log_id)}


@shared_task
def check_provider_health_task(provider_id):
    """Run a lightweight connectivity check for one provider and record the result."""
    provider = EmailProvider.objects.active().filter(pk=provider_id).first()
    if provider is None:
        return {"status": "missing", "id": str(provider_id)}

    healthy, error = get_provider(provider).health_check()
    provider.last_health_check_at = timezone.now()
    provider.last_health_check_error = "" if healthy else error
    provider.save(update_fields=["last_health_check_at", "last_health_check_error"])
    return {"status": "ok" if healthy else "unhealthy", "id": str(provider_id)}


@shared_task
def check_all_providers_health_task():
    """Beat entry point: dispatch a health check for every active provider."""
    provider_ids = list(EmailProvider.objects.active().values_list("id", flat=True))
    for provider_id in provider_ids:
        check_provider_health_task.delay(provider_id)
    return {"dispatched": len(provider_ids)}


@shared_task(bind=True, max_retries=5)
def check_domain_dns_task(self, domain_id):
    """Register the domain with its provider (first run) or re-check DNS
    (subsequent runs), syncing ``Domain.status``/``DomainDnsRecord`` rows."""
    domain = Domain.objects.select_related("provider").filter(pk=domain_id).first()
    if domain is None:
        return {"status": "missing", "id": str(domain_id)}

    provider_impl = get_provider(domain.provider)
    try:
        if domain.provider_domain_id:
            provider_impl.check_domain(domain)
        else:
            provider_impl.register_domain(domain)
    except Exception as exc:
        domain.status = DomainStatus.FAILED
        domain.last_error = str(exc)
        domain.dns_checked_at = timezone.now()
        domain.save(
            update_fields=["status", "last_error", "dns_checked_at", "updated_at"]
        )
        raise self.retry(exc=exc, countdown=min(60 * 2**self.request.retries, 3600))
    return {"status": domain.status, "id": str(domain_id)}


@shared_task
def check_pending_domains_dns_task():
    """Beat entry point: re-check DNS for every domain not yet verified."""
    domain_ids = list(
        Domain.objects.filter(is_active=True)
        .exclude(status=DomainStatus.VERIFIED)
        .values_list("id", flat=True)
    )
    for domain_id in domain_ids:
        check_domain_dns_task.delay(domain_id)
    return {"dispatched": len(domain_ids)}


@shared_task
def retry_stale_webhook_logs_task():
    """Beat entry point: re-enqueue webhook logs stuck in pending/processing/failed.

    Catches rows whose Celery task never ran (broker hiccup) or whose worker
    crashed mid-processing (``locked_at`` set but never finished).
    """
    stale_before = timezone.now() - timedelta(
        minutes=settings.WEBHOOK_LOG_RETRY_STALE_MINUTES
    )
    stale_log_ids = list(
        ProviderWebhookLog.objects.filter(
            status__in=RETRYABLE_STATUSES,
            attempt_count__lt=settings.WEBHOOK_LOG_MAX_ATTEMPTS,
        )
        .filter(
            models.Q(locked_at__isnull=True, received_at__lt=stale_before)
            | models.Q(locked_at__lt=stale_before)
        )
        .values_list("id", flat=True)
    )
    for log_id in stale_log_ids:
        process_webhook_log_task.delay(log_id)
    return {"dispatched": len(stale_log_ids)}


@shared_task
def cleanup_daily_send_logs_task():
    """Beat entry point: drop DailyDomainSendLog rows past the retention window."""
    cutoff = timezone.now().date() - timedelta(
        days=settings.DAILY_SEND_LOG_RETENTION_DAYS
    )
    deleted, _ = DailyDomainSendLog.objects.filter(date__lt=cutoff).delete()
    return {"deleted": deleted}


@shared_task
def redact_old_webhook_payloads_task():
    """Beat entry point: blank out ``payload``/``headers`` on webhook logs
    older than ``WEBHOOK_LOG_PAYLOAD_RETENTION_DAYS``.

    Raw payloads duplicate storage already retained elsewhere (message bodies
    live on ``EmailMessage``, attachment bytes in S3 via ``EmailAttachment``)
    and can carry full email content indefinitely with no equivalent of
    ``cleanup_daily_send_logs_task``. Only rows past ``RETRYABLE_STATUSES``
    are touched, so nothing still eligible for the stale-retry sweep loses
    the payload it needs to be reprocessed.
    """
    cutoff = timezone.now() - timedelta(
        days=settings.WEBHOOK_LOG_PAYLOAD_RETENTION_DAYS
    )
    updated = (
        ProviderWebhookLog.objects.filter(received_at__lt=cutoff)
        .exclude(status__in=RETRYABLE_STATUSES)
        .exclude(payload={}, headers={})
        .update(payload={}, headers={})
    )
    return {"redacted": updated}


@shared_task
def check_catch_all_coverage_task():
    """Beat entry point: log a warning for every domain with receive-enabled
    mailboxes but no catch-all — otherwise mail to an unrecognized address is
    dropped with nothing visible beyond a webhook log row. See
    ``providers.catch_all_coverage`` and the ``check_catch_all_coverage``
    management command (same logic, for ad hoc/CI use)."""
    flagged = find_domains_missing_catch_all(days=7)
    for domain, mailbox_count, dropped_count in flagged:
        logger.warning(
            "Domain %s has %d receive-enabled mailbox(es) but no catch-all mailbox; "
            "%d message(s) dropped for 'no mailbox matched' in the last 7 days",
            domain.name,
            mailbox_count,
            dropped_count,
        )
    return {"flagged_domains": len(flagged)}
