"""``reserve_send_slot`` must check-and-increment atomically: two reservation
attempts against the same (domain, date) row must not both succeed once the
limit is reached, even when a naive read-then-write would have raced.
"""

import base64

import pytest
from django.utils import timezone

from hedwig.models import EmailMessage
from providers.models import DailyDomainSendLog
from providers.postmark import TransientSendError
from providers.sending import send_with_provider

pytestmark = pytest.mark.django_db


def test_reserve_send_slot_admits_up_to_the_limit_then_rejects(domain):
    domain.max_send_per_day = 2
    domain.save(update_fields=["max_send_per_day"])

    assert DailyDomainSendLog.objects.reserve_send_slot(domain, limit=2) is True
    assert DailyDomainSendLog.objects.reserve_send_slot(domain, limit=2) is True
    # Third reservation must be rejected, not silently admitted.
    assert DailyDomainSendLog.objects.reserve_send_slot(domain, limit=2) is False

    log = DailyDomainSendLog.objects.get(domain=domain, date=timezone.now().date())
    assert log.sent_count == 2


def test_release_send_slot_gives_back_a_reservation(domain):
    domain.max_send_per_day = 1
    domain.save(update_fields=["max_send_per_day"])

    assert DailyDomainSendLog.objects.reserve_send_slot(domain, limit=1) is True
    assert DailyDomainSendLog.objects.reserve_send_slot(domain, limit=1) is False

    DailyDomainSendLog.objects.release_send_slot(domain)

    # The released slot is available again.
    assert DailyDomainSendLog.objects.reserve_send_slot(domain, limit=1) is True


def test_release_send_slot_does_not_go_negative(domain):
    DailyDomainSendLog.objects.reserve_send_slot(domain, limit=None)

    DailyDomainSendLog.objects.release_send_slot(domain)
    # A second release with no matching reservation left must not error or
    # drive the counter below zero.
    DailyDomainSendLog.objects.release_send_slot(domain)

    log = DailyDomainSendLog.objects.get(domain=domain, date=timezone.now().date())
    assert log.sent_count == 0


def test_reserved_slot_is_released_when_materialize_attachments_fails(
    mailbox, sender_identity, regular_user, domain, monkeypatch
):
    """materialize_attachments (storage upload) runs after the slot is
    reserved but before the provider is ever called. If it raises, the
    reservation must still be released — otherwise a storage outage burns
    down a domain's daily limit without a single message going out.
    """
    content = base64.b64encode(b"secret file bytes").decode()
    message, attempt = EmailMessage.objects.create_outbound_message(
        mailbox=mailbox,
        created_by=regular_user,
        sender_identity=sender_identity,
        to_addresses=[{"email": "customer@example.com"}],
        subject="Hello",
        body_text="Hi there",
        attachments=[
            {
                "filename": "secret.txt",
                "content_type": "text/plain",
                "content": content,
            }
        ],
    )
    monkeypatch.setattr(
        "providers.sending.store_attachment_content",
        lambda *args, **kwargs: ("", "", "checksum", len(b"secret file bytes")),
    )

    with pytest.raises(TransientSendError):
        send_with_provider(message, attempt)

    log = DailyDomainSendLog.objects.get(domain=domain, date=timezone.now().date())
    assert log.sent_count == 0
