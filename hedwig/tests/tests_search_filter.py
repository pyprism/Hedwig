"""``?search=is:starred`` / ``is:important`` must only match the requesting
user's own per-user state, not another user's state on a shared mailbox.
"""

import pytest

from hedwig.models import (
    EmailMessage,
    EmailMessageUserState,
    EmailThread,
    UserMailboxAccess,
)
from utils.enums import AccessType, DirectionType, EmailStatus, MailboxPermissionType

pytestmark = pytest.mark.django_db


def _message(mailbox, thread, subject="Hi"):
    return EmailMessage.objects.create(
        mailbox=mailbox,
        thread=thread,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        from_address="bob@example.com",
        from_name="Bob",
        subject=subject,
        to_addresses=[{"email": mailbox.email_address, "name": ""}],
    )


@pytest.fixture
def other_user_mailbox_access(other_user, mailbox):
    return UserMailboxAccess.objects.create(
        user=other_user,
        access_type=AccessType.MAILBOX,
        mailbox=mailbox,
        permission=MailboxPermissionType.READ_WRITE,
    )


def test_search_is_starred_does_not_leak_other_users_state(
    api_client,
    regular_user,
    other_user,
    mailbox,
    mailbox_access,
    other_user_mailbox_access,
):
    thread = EmailThread.objects.create(mailbox=mailbox, subject="Shared thread")
    message = _message(mailbox, thread)
    EmailMessageUserState.objects.create(
        user=other_user, message=message, folder="inbox", is_starred=True
    )

    api_client.force_authenticate(regular_user)
    response = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "search": "is:starred"}
    )

    assert response.status_code == 200
    assert response.data["results"] == []


def test_search_is_important_does_not_leak_other_users_state(
    api_client,
    regular_user,
    other_user,
    mailbox,
    mailbox_access,
    other_user_mailbox_access,
):
    thread = EmailThread.objects.create(mailbox=mailbox, subject="Shared thread")
    message = _message(mailbox, thread)
    EmailMessageUserState.objects.create(
        user=other_user, message=message, folder="inbox", is_important=True
    )

    api_client.force_authenticate(regular_user)
    response = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "search": "is:important"}
    )

    assert response.status_code == 200
    assert response.data["results"] == []

    EmailMessageUserState.objects.create(
        user=regular_user, message=message, folder="inbox", is_important=True
    )
    own = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "search": "is:important"}
    )
    assert {r["id"] for r in own.data["results"]} == {str(thread.id)}


def test_message_list_exposes_is_important_from_requesting_users_state(
    api_client, regular_user, mailbox, mailbox_access
):
    thread = EmailThread.objects.create(mailbox=mailbox, subject="Thread")
    message = _message(mailbox, thread)
    EmailMessageUserState.objects.create(
        user=regular_user, message=message, folder="inbox", is_important=True
    )

    api_client.force_authenticate(regular_user)
    response = api_client.get("/api/mail/messages/", {"thread": thread.id})

    assert response.status_code == 200
    result = next(r for r in response.data["results"] if r["id"] == str(message.id))
    assert result["is_important"] is True
