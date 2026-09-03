"""Mailbox inbound-quota enforcement must read the current DB value under a
row lock, not trust a possibly-stale in-memory ``Mailbox`` instance — two
concurrent ingests (e.g. two Celery workers) must not both be admitted over
quota.
"""

import pytest

from hedwig.models import Mailbox
from providers.base import NormalizedAddress, NormalizedInboundMessage
from providers.ingest import MailboxQuotaExceeded, create_inbound_message
from providers.models import ProviderWebhookLog

pytestmark = pytest.mark.django_db


def _normalized(**overrides):
    defaults = dict(
        from_address="customer@external.com",
        from_name="Customer",
        to=[NormalizedAddress(email="support@example.com", name="Support")],
        subject="Hi",
        body_text="x" * 1000,
        provider_message_id="pm-quota-1",
    )
    defaults.update(overrides)
    return NormalizedInboundMessage(**defaults)


def _raw_webhook(domain):
    return ProviderWebhookLog.objects.create(domain=domain, payload={})


def test_quota_check_uses_fresh_db_value_not_stale_caller_instance(
    postmark_provider, mailbox
):
    mailbox.quota_bytes = 1000
    mailbox.used_bytes = 0
    mailbox.save(update_fields=["quota_bytes", "used_bytes"])

    # Simulate a concurrent ingest for the same mailbox having already landed
    # and pushed used_bytes near the cap, *after* this caller loaded its
    # (now stale) `mailbox` instance.
    Mailbox.objects.filter(pk=mailbox.pk).update(used_bytes=990)

    with pytest.raises(MailboxQuotaExceeded):
        create_inbound_message(
            postmark_provider,
            mailbox,  # stale: still thinks used_bytes == 0
            "support@example.com",
            _normalized(body_text="x" * 100),
            _raw_webhook(mailbox.domain),
        )


def test_quota_check_admits_when_fresh_db_value_has_room(postmark_provider, mailbox):
    mailbox.quota_bytes = 1_000_000
    mailbox.used_bytes = 0
    mailbox.save(update_fields=["quota_bytes", "used_bytes"])

    message, created = create_inbound_message(
        postmark_provider,
        mailbox,
        "support@example.com",
        _normalized(),
        _raw_webhook(mailbox.domain),
    )
    assert created is True
    mailbox.refresh_from_db()
    assert mailbox.used_bytes == message.size_bytes
