from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import models
from django.utils import timezone

from providers.ingest import process_webhook_log
from providers.models import DailyDomainSendLog, EmailProvider, ProviderWebhookLog
from providers.registry import get_provider
from utils.enums import ProviderWebhookStatus

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
    raw_webhook = (
        ProviderWebhookLog.objects.select_related("provider", "domain")
        .filter(pk=webhook_log_id)
        .first()
    )
    if raw_webhook is None:
        return {"status": "missing", "id": str(webhook_log_id)}

    if raw_webhook.status not in RETRYABLE_STATUSES:
        return {"status": raw_webhook.status, "id": str(webhook_log_id)}

    raw_webhook.status = ProviderWebhookStatus.PROCESSING
    raw_webhook.locked_at = timezone.now()
    raw_webhook.attempt_count += 1
    raw_webhook.save(update_fields=["status", "locked_at", "attempt_count"])

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
