"""``process_webhook_log_task`` claims its row with a single conditional
UPDATE, so two concurrent deliveries for the same webhook_log_id (a broker
redelivery landing alongside the stale-retry sweep) cannot both proceed to
call ``process_webhook_log``.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.utils import timezone

from providers.models import ProviderWebhookLog
from providers.tasks import process_webhook_log_task
from utils.enums import ProviderWebhookStatus

pytestmark = pytest.mark.django_db


def test_task_skips_processing_when_row_already_claimed_by_another_worker(
    domain, postmark_provider
):
    log = ProviderWebhookLog.objects.create(
        provider=postmark_provider,
        domain=domain,
        payload={"ToFull": [], "TextBody": "irrelevant"},
        status=ProviderWebhookStatus.PROCESSING,  # already claimed elsewhere
    )

    with patch("providers.tasks.process_webhook_log") as mocked:
        result = process_webhook_log_task(log.pk)

    mocked.assert_not_called()
    assert result == {"status": ProviderWebhookStatus.PROCESSING, "id": str(log.pk)}


def test_task_reclaims_a_stale_processing_row(domain, postmark_provider):
    # Crash recovery still works: a PROCESSING row whose lock is older than
    # the stale threshold (the same one the sweep uses) IS reclaimable.
    stale_locked_at = timezone.now() - timedelta(
        minutes=settings.WEBHOOK_LOG_RETRY_STALE_MINUTES + 5
    )
    log = ProviderWebhookLog.objects.create(
        provider=postmark_provider,
        domain=domain,
        payload={"ToFull": [], "TextBody": "irrelevant"},
        status=ProviderWebhookStatus.PROCESSING,
        locked_at=stale_locked_at,
    )

    with patch("providers.tasks.process_webhook_log") as mocked:
        mocked.side_effect = lambda raw_webhook: raw_webhook
        process_webhook_log_task(log.pk)

    mocked.assert_called_once()


def test_task_claims_and_processes_a_pending_row(domain, postmark_provider):
    log = ProviderWebhookLog.objects.create(
        provider=postmark_provider,
        domain=domain,
        payload={"ToFull": [], "TextBody": "irrelevant"},
        status=ProviderWebhookStatus.PENDING,
    )

    with patch("providers.tasks.process_webhook_log") as mocked:
        mocked.side_effect = lambda raw_webhook: raw_webhook
        process_webhook_log_task(log.pk)

    mocked.assert_called_once()
    claimed_arg = mocked.call_args[0][0]
    assert claimed_arg.status == ProviderWebhookStatus.PROCESSING
    log.refresh_from_db()
    assert log.attempt_count == 1
