"""Domains with receive-enabled mailboxes but no catch-all mailbox should be
flagged — both by the management command and the periodic Celery task —
instead of silently dropping mail to unrecognized addresses with no signal.
"""

import io

import pytest
from django.core.management import call_command

from hedwig.models import Mailbox
from providers.catch_all_coverage import find_domains_missing_catch_all
from providers.models import ProviderWebhookLog
from providers.tasks import check_catch_all_coverage_task
from utils.enums import ProviderWebhookStatus

pytestmark = pytest.mark.django_db


def test_domain_without_catch_all_is_flagged(mailbox):
    flagged = find_domains_missing_catch_all()

    assert len(flagged) == 1
    domain, mailbox_count, dropped_count = flagged[0]
    assert domain.id == mailbox.domain_id
    assert mailbox_count == 1
    assert dropped_count == 0


def test_domain_with_catch_all_is_not_flagged(mailbox):
    mailbox.is_catch_all = True
    mailbox.save(update_fields=["is_catch_all"])

    assert find_domains_missing_catch_all() == []


def test_dropped_count_reflects_recent_ignored_webhooks(mailbox):
    ProviderWebhookLog.objects.create(
        domain=mailbox.domain,
        payload={},
        status=ProviderWebhookStatus.IGNORED,
        error_message="No mailbox matched the inbound recipients.",
    )
    ProviderWebhookLog.objects.create(
        domain=mailbox.domain,
        payload={},
        status=ProviderWebhookStatus.PROCESSED,
    )

    flagged = find_domains_missing_catch_all()
    assert flagged[0][2] == 1


def test_domain_with_no_receiving_mailboxes_is_not_flagged(domain):
    Mailbox.objects.create(
        domain=domain, local_part="disabled", receive_enabled=False, is_active=True
    )

    assert find_domains_missing_catch_all() == []


def test_management_command_reports_flagged_domain(mailbox):
    out = io.StringIO()
    call_command("check_catch_all_coverage", stdout=out)
    assert mailbox.domain.name in out.getvalue()


def test_management_command_strict_exits_nonzero_when_flagged(mailbox):
    with pytest.raises(SystemExit) as exc_info:
        call_command("check_catch_all_coverage", "--strict")
    assert exc_info.value.code == 1


def test_task_logs_a_warning_per_flagged_domain(mailbox, caplog):
    with caplog.at_level("WARNING"):
        result = check_catch_all_coverage_task()

    assert result == {"flagged_domains": 1}
    assert mailbox.domain.name in caplog.text
