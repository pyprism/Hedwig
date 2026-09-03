"""Self-service ``GET /api/mail/mailbox-accesses/mine/`` — a non-staff user
can see their own access grants without needing staff permission, but only
ever their own rows, and cannot write through this path.
"""

import pytest

pytestmark = pytest.mark.django_db

MINE_URL = "/api/mail/mailbox-accesses/mine/"


def test_regular_user_sees_only_their_own_grant(
    api_client, regular_user, other_user, mailbox, mailbox_access
):
    from hedwig.models import UserMailboxAccess
    from utils.enums import AccessType, MailboxPermissionType

    UserMailboxAccess.objects.create(
        user=other_user,
        access_type=AccessType.MAILBOX,
        mailbox=mailbox,
        permission=MailboxPermissionType.READ_ONLY,
    )

    api_client.force_authenticate(regular_user)
    response = api_client.get(MINE_URL)

    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == 1
    assert str(results[0]["user"]) == str(regular_user.id)
    assert str(results[0]["mailbox"]) == str(mailbox.id)


def test_mine_requires_authentication(api_client):
    response = api_client.get(MINE_URL)
    assert response.status_code == 401


def test_mine_is_read_only(api_client, regular_user, mailbox, mailbox_access):
    # No POST handler is registered for this action (methods=["get"] only);
    # a non-staff caller gets 403 (falls back to the viewset's base
    # IsStaffUser permission for the unmapped method) rather than ever
    # reaching a write path.
    api_client.force_authenticate(regular_user)
    response = api_client.post(MINE_URL, {}, format="json")
    assert response.status_code == 403
