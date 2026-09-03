"""``redact_old_webhook_payloads_task`` blanks out payload/headers on old,
terminal webhook logs, but leaves recent or still-retryable rows untouched."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from providers.models import ProviderWebhookLog
from providers.tasks import redact_old_webhook_payloads_task
from utils.enums import ProviderWebhookStatus

pytestmark = pytest.mark.django_db


def _old_log(domain, status, days_old=None):
    log = ProviderWebhookLog.objects.create(
        domain=domain,
        payload={"TextBody": "sensitive content"},
        headers={"X-Something": "value"},
        status=status,
    )
    if days_old is not None:
        stale_at = timezone.now() - timedelta(days=days_old)
        ProviderWebhookLog.objects.filter(pk=log.pk).update(received_at=stale_at)
        log.refresh_from_db()
    return log


def test_redacts_old_processed_log(domain):
    log = _old_log(
        domain,
        ProviderWebhookStatus.PROCESSED,
        days_old=settings.WEBHOOK_LOG_PAYLOAD_RETENTION_DAYS + 1,
    )

    result = redact_old_webhook_payloads_task()

    assert result == {"redacted": 1}
    log.refresh_from_db()
    assert log.payload == {}
    assert log.headers == {}


def test_does_not_redact_recent_log(domain):
    log = _old_log(domain, ProviderWebhookStatus.PROCESSED, days_old=1)

    redact_old_webhook_payloads_task()

    log.refresh_from_db()
    assert log.payload == {"TextBody": "sensitive content"}


def test_does_not_redact_still_retryable_log(domain):
    log = _old_log(
        domain,
        ProviderWebhookStatus.PENDING,
        days_old=settings.WEBHOOK_LOG_PAYLOAD_RETENTION_DAYS + 1,
    )

    redact_old_webhook_payloads_task()

    log.refresh_from_db()
    assert log.payload == {"TextBody": "sensitive content"}
