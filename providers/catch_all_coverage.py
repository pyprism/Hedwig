"""Shared logic for detecting domains that are silently dropping inbound mail
because they have receive-enabled mailboxes but no catch-all mailbox
configured. Used by both the ``check_catch_all_coverage`` management command
and the periodic ``check_catch_all_coverage_task`` Celery task.
"""

from datetime import timedelta

from django.utils import timezone

from hedwig.models import Mailbox
from providers.models import Domain, ProviderWebhookLog
from utils.enums import ProviderWebhookStatus


def find_domains_missing_catch_all(days=7):
    """Return a list of ``(domain, receiving_mailbox_count, dropped_count)``
    for every active, inbound-enabled domain that has at least one
    receive-enabled mailbox but none marked ``is_catch_all``."""
    since = timezone.now() - timedelta(days=days)
    flagged = []

    for domain in Domain.objects.filter(is_active=True, inbound_enabled=True):
        receiving_mailboxes = Mailbox.objects.filter(
            domain=domain, is_active=True, receive_enabled=True
        )
        if not receiving_mailboxes.exists():
            continue
        if receiving_mailboxes.filter(is_catch_all=True).exists():
            continue

        dropped_count = ProviderWebhookLog.objects.filter(
            domain=domain,
            status=ProviderWebhookStatus.IGNORED,
            error_message__icontains="No mailbox matched",
            received_at__gte=since,
        ).count()
        flagged.append((domain, receiving_mailboxes.count(), dropped_count))

    return flagged
