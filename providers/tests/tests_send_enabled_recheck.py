"""``mailbox.send_enabled``/``domain.outbound_enabled`` must be re-checked at
actual dispatch time, not just at compose time — an admin can disable sending
after a message is already queued (retry backoff, or a scheduled_at days out).
"""

import pytest

from hedwig.models import EmailMessage, OutboundSendAttempt
from providers.postmark import PermanentSendError
from providers.sending import send_with_provider
from utils.enums import DirectionType, EmailStatus, SendAttemptStatus

pytestmark = pytest.mark.django_db


def _queued_outbound_message(mailbox, sender_identity):
    message = EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.OUTBOUND,
        status=EmailStatus.QUEUED,
        from_address=sender_identity.email,
        to_addresses=[{"email": "customer@example.com", "name": ""}],
        subject="Hi",
        body_text="Hello",
    )
    attempt = OutboundSendAttempt.objects.create(
        message=message,
        provider=mailbox.domain.provider,
        status=SendAttemptStatus.PENDING,
    )
    return message, attempt


def test_dispatch_rejects_when_mailbox_send_disabled_after_compose(
    mailbox, sender_identity
):
    message, attempt = _queued_outbound_message(mailbox, sender_identity)
    mailbox.send_enabled = False
    mailbox.save(update_fields=["send_enabled"])

    with pytest.raises(PermanentSendError):
        send_with_provider(message, attempt)

    attempt.refresh_from_db()
    assert attempt.status == SendAttemptStatus.FAILED


def test_dispatch_rejects_when_domain_outbound_disabled_after_compose(
    mailbox, sender_identity, domain
):
    message, attempt = _queued_outbound_message(mailbox, sender_identity)
    domain.outbound_enabled = False
    domain.save(update_fields=["outbound_enabled"])

    with pytest.raises(PermanentSendError):
        send_with_provider(message, attempt)

    attempt.refresh_from_db()
    assert attempt.status == SendAttemptStatus.FAILED
