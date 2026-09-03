"""Dedup fallbacks for inbound messages and delivery events when the provider
payload doesn't carry its own id — closing the "no dedup at any layer" and
"undercounts engagement" gaps.
"""

import pytest

from hedwig.models import EmailMessage
from providers.base import (
    NormalizedAddress,
    NormalizedDeliveryEvent,
    NormalizedInboundMessage,
)
from providers.ingest import create_delivery_event, create_inbound_message
from providers.models import DeliveryEvent, ProviderWebhookLog
from utils.enums import DirectionType, EmailStatus

pytestmark = pytest.mark.django_db


def _raw_webhook(domain):
    return ProviderWebhookLog.objects.create(domain=domain, payload={})


def test_inbound_falls_back_to_rfc_message_id_when_provider_id_missing(
    postmark_provider, mailbox
):
    normalized = NormalizedInboundMessage(
        from_address="customer@external.com",
        from_name="Customer",
        to=[NormalizedAddress(email="support@example.com", name="Support")],
        subject="Hi",
        body_text="Hello",
        rfc_message_id="<abc123@external.com>",
        provider_message_id="",  # provider omitted its own id
    )
    raw_webhook = _raw_webhook(mailbox.domain)

    first, created_first = create_inbound_message(
        postmark_provider, mailbox, "support@example.com", normalized, raw_webhook
    )
    assert created_first is True

    # A redelivery of the same payload variant (still no provider_message_id)
    # must be recognized as the same message via rfc_message_id, not
    # duplicated.
    second, created_second = create_inbound_message(
        postmark_provider, mailbox, "support@example.com", normalized, raw_webhook
    )
    assert created_second is False
    assert second.id == first.id
    assert (
        EmailMessage.objects.filter(
            mailbox=mailbox, rfc_message_id="<abc123@external.com>"
        ).count()
        == 1
    )


@pytest.fixture
def outbound_message(mailbox, postmark_provider):
    message = EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.OUTBOUND,
        status=EmailStatus.SENT,
        from_address=mailbox.email_address,
        to_addresses=[{"email": "customer@external.com", "name": "Customer"}],
        subject="Your invoice",
        provider=postmark_provider,
        provider_message_id="pm-out-1",
    )
    return message


def test_delivery_events_without_provider_event_id_are_not_collapsed(
    outbound_message,
):
    raw_webhook = _raw_webhook(outbound_message.mailbox.domain)

    for _ in range(3):
        create_delivery_event(
            outbound_message.mailbox.domain,
            NormalizedDeliveryEvent(
                event_type="opened",
                provider_message_id="pm-out-1",
                provider_event_id="",  # Postmark doesn't always supply one
                recipient="customer@external.com",
            ),
            raw_webhook,
        )

    # Three real opens from the same recipient must all be recorded, not
    # collapsed into a single row by an empty-string dedup key.
    assert (
        DeliveryEvent.objects.filter(
            message=outbound_message,
            event_type="opened",
            recipient="customer@external.com",
        ).count()
        == 3
    )


def test_delivery_events_with_provider_event_id_still_dedupe(outbound_message):
    raw_webhook = _raw_webhook(outbound_message.mailbox.domain)

    for _ in range(3):
        create_delivery_event(
            outbound_message.mailbox.domain,
            NormalizedDeliveryEvent(
                event_type="delivered",
                provider_message_id="pm-out-1",
                provider_event_id="evt-delivered-1",
                recipient="customer@external.com",
            ),
            raw_webhook,
        )

    assert (
        DeliveryEvent.objects.filter(
            message=outbound_message,
            event_type="delivered",
            provider_event_id="evt-delivered-1",
        ).count()
        == 1
    )
