"""Subject-fallback thread matching (no In-Reply-To/References) reuses an
existing thread rather than starting a new one for each message. The
underlying race between two brand-new-conversation messages is closed by the
mailbox row lock ``create_inbound_message`` holds for the whole transaction
(see the docstring on ``update_thread_for_message``) — this test covers the
sequential correctness the lock is protecting.
"""

import pytest

from providers.base import NormalizedAddress, NormalizedInboundMessage
from providers.ingest import create_inbound_message
from providers.models import ProviderWebhookLog

pytestmark = pytest.mark.django_db


def _normalized(provider_message_id, subject="Order #42"):
    return NormalizedInboundMessage(
        from_address="customer@external.com",
        from_name="Customer",
        to=[NormalizedAddress(email="support@example.com", name="Support")],
        subject=subject,
        body_text="Hello",
        provider_message_id=provider_message_id,
    )


def test_matching_subject_with_no_threading_headers_joins_same_thread(
    postmark_provider, mailbox
):
    raw_webhook = ProviderWebhookLog.objects.create(domain=mailbox.domain, payload={})

    first, _ = create_inbound_message(
        postmark_provider,
        mailbox,
        "support@example.com",
        _normalized("pm-subj-1"),
        raw_webhook,
    )
    second, _ = create_inbound_message(
        postmark_provider,
        mailbox,
        "support@example.com",
        _normalized("pm-subj-2", subject="Re: Order #42"),
        raw_webhook,
    )

    assert first.thread_id is not None
    assert first.thread_id == second.thread_id
    second.thread.refresh_from_db()
    assert second.thread.message_count == 2
