"""``POST /api/mail/messages/bulk-permanent-delete/`` — hard-delete several
messages in one request, with the same write-access rule as the
single-message ``permanent-delete`` action.
"""

import pytest

from hedwig.models import EmailMessage
from utils.enums import (
    AccessType,
    DirectionType,
    EmailStatus,
    Folder,
    MailboxPermissionType,
)

pytestmark = pytest.mark.django_db

BULK_DELETE_URL = "/api/mail/messages/bulk-permanent-delete/"


def _trashed_message(mailbox, subject="Spam"):
    return EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=Folder.TRASH,
        from_address="customer@example.com",
        subject=subject,
    )


def test_owner_can_bulk_delete_their_own_messages(
    api_client, regular_user, mailbox, mailbox_access
):
    messages = [_trashed_message(mailbox, f"Spam {i}") for i in range(3)]
    api_client.force_authenticate(regular_user)

    response = api_client.post(
        BULK_DELETE_URL, {"ids": [str(m.id) for m in messages]}, format="json"
    )

    assert response.status_code == 200
    assert response.data == {"deleted": 3}
    assert EmailMessage.objects.filter(id__in=[m.id for m in messages]).count() == 0


def test_read_only_user_cannot_bulk_delete(api_client, other_user, mailbox):
    from hedwig.models import UserMailboxAccess

    UserMailboxAccess.objects.create(
        user=other_user,
        access_type=AccessType.MAILBOX,
        mailbox=mailbox,
        permission=MailboxPermissionType.READ_ONLY,
    )
    messages = [_trashed_message(mailbox)]
    api_client.force_authenticate(other_user)

    response = api_client.post(
        BULK_DELETE_URL, {"ids": [str(m.id) for m in messages]}, format="json"
    )

    assert response.status_code == 403
    assert EmailMessage.objects.filter(id=messages[0].id).exists()


def test_bulk_delete_requires_non_empty_ids(api_client, regular_user, mailbox_access):
    api_client.force_authenticate(regular_user)
    response = api_client.post(BULK_DELETE_URL, {"ids": []}, format="json")
    assert response.status_code == 400


def test_bulk_delete_rejects_unknown_ids(
    api_client, regular_user, mailbox, mailbox_access
):
    message = _trashed_message(mailbox)
    api_client.force_authenticate(regular_user)

    response = api_client.post(
        BULK_DELETE_URL,
        {"ids": [str(message.id), "00000000-0000-0000-0000-000000000000"]},
        format="json",
    )

    assert response.status_code == 404
    assert EmailMessage.objects.filter(id=message.id).exists()
