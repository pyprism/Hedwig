"""Write-access checks around cancelling a scheduled send (explicit `/cancel/`
and the implicit cancel-on-trash side effect), plus a concurrency-safety check
for the per-user state upsert.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import transaction
from django.utils import timezone

from hedwig.models import EmailMessage, EmailMessageUserState, OutboundSendAttempt
from utils.enums import (
    AccessType,
    EmailStatus,
    MailboxPermissionType,
    SendAttemptStatus,
)

pytestmark = pytest.mark.django_db

SEND_URL = "/api/mail/messages/send/"


def _send_payload(**overrides):
    payload = {
        "mailbox": None,
        "to": [{"email": "customer@example.com", "name": "Customer"}],
        "subject": "Hello",
        "body_text": "Hi there",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def read_only_access(other_user, mailbox):
    from hedwig.models import UserMailboxAccess

    return UserMailboxAccess.objects.create(
        user=other_user,
        access_type=AccessType.MAILBOX,
        mailbox=mailbox,
        permission=MailboxPermissionType.READ_ONLY,
    )


def _schedule_send(api_client, regular_user, mailbox, sender_identity):
    api_client.force_authenticate(regular_user)
    scheduled_at = timezone.now() + timedelta(hours=1)
    with patch("hedwig.views.send_email_message_task.apply_async"):
        with transaction.atomic():
            response = api_client.post(
                SEND_URL,
                _send_payload(
                    mailbox=str(mailbox.id), scheduled_at=scheduled_at.isoformat()
                ),
                format="json",
            )
    assert response.status_code == 202, response.data
    return response.data["id"]


def test_read_only_user_cannot_cancel_another_users_scheduled_send(
    api_client,
    regular_user,
    other_user,
    mailbox,
    mailbox_access,
    read_only_access,
    sender_identity,
):
    message_id = _schedule_send(api_client, regular_user, mailbox, sender_identity)

    api_client.force_authenticate(other_user)
    response = api_client.post(f"/api/mail/messages/{message_id}/cancel/")

    assert response.status_code == 403
    message = EmailMessage.objects.get(pk=message_id)
    assert message.status == EmailStatus.QUEUED


def test_read_only_user_trashing_their_view_does_not_cancel_shared_send(
    api_client,
    regular_user,
    other_user,
    mailbox,
    mailbox_access,
    read_only_access,
    sender_identity,
):
    message_id = _schedule_send(api_client, regular_user, mailbox, sender_identity)

    api_client.force_authenticate(other_user)
    response = api_client.patch(
        f"/api/mail/messages/{message_id}/state/",
        {"folder": "trash"},
        format="json",
    )

    assert response.status_code == 200
    message = EmailMessage.objects.get(pk=message_id)
    # The shared send is untouched...
    assert message.status == EmailStatus.QUEUED
    assert (
        OutboundSendAttempt.objects.get(message=message).status
        == SendAttemptStatus.PENDING
    )
    # ...but the read-only user's own per-user view did move to trash.
    state = EmailMessageUserState.objects.get(user=other_user, message=message)
    assert state.folder == "trash"


def test_state_upsert_does_not_500_on_concurrent_create(regular_user, mailbox):
    from hedwig.models import EmailThread

    thread = EmailThread.objects.create(mailbox=mailbox, subject="Race")
    message = EmailMessage.objects.create(
        mailbox=mailbox,
        thread=thread,
        direction="inbound",
        status=EmailStatus.RECEIVED,
        from_address="bob@example.com",
        subject="Hi",
        to_addresses=[{"email": mailbox.email_address, "name": ""}],
    )

    # Simulate the loser of a race: a state row is created concurrently
    # between another caller's existence-check and its own insert attempt.
    EmailMessageUserState.objects.create(
        user=regular_user, message=message, folder="inbox", is_starred=False
    )

    # upsert() must not raise IntegrityError even though a row now exists.
    state = EmailMessageUserState.objects.upsert(
        user=regular_user, message=message, values={"is_starred": True}
    )
    assert state.is_starred is True
    assert (
        EmailMessageUserState.objects.filter(user=regular_user, message=message).count()
        == 1
    )
