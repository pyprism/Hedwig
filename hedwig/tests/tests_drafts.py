import base64

import pytest

from hedwig.models import EmailMessage
from utils.enums import EmailStatus, Folder

pytestmark = pytest.mark.django_db

DRAFT_URL = "/api/mail/messages/draft/"


def _draft_url(message_id):
    return f"/api/mail/messages/{message_id}/draft/"


@pytest.fixture
def authed_client(api_client, regular_user, mailbox_access):
    api_client.force_authenticate(regular_user)
    return api_client


def test_create_draft_minimal(authed_client, mailbox):
    response = authed_client.post(
        DRAFT_URL,
        {"mailbox": str(mailbox.id), "subject": "Draft subject"},
        format="json",
    )

    assert response.status_code == 201
    message = EmailMessage.objects.get(pk=response.data["id"])
    assert message.status == EmailStatus.DRAFT
    assert message.folder == Folder.DRAFTS
    assert message.subject == "Draft subject"
    # A draft is not threaded or queued, so no send attempt is created.
    assert message.send_attempts.count() == 0


def test_create_draft_with_attachment(authed_client, mailbox):
    content = base64.b64encode(b"draft attachment bytes").decode()
    response = authed_client.post(
        DRAFT_URL,
        {
            "mailbox": str(mailbox.id),
            "subject": "With file",
            "body_text": "see attached",
            "attachments": [
                {
                    "filename": "note.txt",
                    "content_type": "text/plain",
                    "content": content,
                }
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    message = EmailMessage.objects.get(pk=response.data["id"])
    assert message.has_attachments is True
    attachment = message.attachments.get()
    assert attachment.filename == "note.txt"
    assert attachment.metadata["pending_content_b64"] == content


def test_update_draft_replaces_attachments(authed_client, mailbox):
    first = base64.b64encode(b"one").decode()
    create = authed_client.post(
        DRAFT_URL,
        {
            "mailbox": str(mailbox.id),
            "attachments": [
                {"filename": "a.txt", "content_type": "text/plain", "content": first}
            ],
        },
        format="json",
    )
    draft_id = create.data["id"]

    second = base64.b64encode(b"two longer").decode()
    response = authed_client.patch(
        _draft_url(draft_id),
        {
            "subject": "Updated",
            "attachments": [
                {"filename": "b.txt", "content_type": "text/plain", "content": second}
            ],
        },
        format="json",
    )

    assert response.status_code == 200
    message = EmailMessage.objects.get(pk=draft_id)
    assert message.subject == "Updated"
    # The previous attachment set is fully replaced.
    assert message.attachments.count() == 1
    assert message.attachments.get().filename == "b.txt"


def test_owner_can_delete_own_draft(authed_client, mailbox):
    create = authed_client.post(
        DRAFT_URL, {"mailbox": str(mailbox.id), "subject": "Bye"}, format="json"
    )
    draft_id = create.data["id"]

    response = authed_client.delete(f"/api/mail/messages/{draft_id}/")

    assert response.status_code == 204
    assert not EmailMessage.objects.filter(pk=draft_id).exists()


def test_draft_is_threaded_and_visible_in_drafts_folder(authed_client, mailbox):
    create = authed_client.post(
        DRAFT_URL,
        {"mailbox": str(mailbox.id), "subject": "Cross-device"},
        format="json",
    )
    assert create.data["thread"] is not None

    # The dedicated thread makes the draft visible (and editable/sendable) on
    # other devices via the folder-aware threads endpoint.
    listing = authed_client.get(
        f"/api/mail/threads/?mailbox={mailbox.id}&folder=drafts"
    )
    assert listing.status_code == 200
    thread_ids = {str(row["id"]) for row in listing.data["results"]}
    assert str(create.data["thread"]) in thread_ids


def test_update_draft_keeps_attachment_by_reference_and_adds_new(
    authed_client, mailbox
):
    first = base64.b64encode(b"keep me").decode()
    create = authed_client.post(
        DRAFT_URL,
        {
            "mailbox": str(mailbox.id),
            "attachments": [
                {"filename": "keep.txt", "content_type": "text/plain", "content": first}
            ],
        },
        format="json",
    )
    draft_id = create.data["id"]
    kept_id = create.data["attachments"][0]["id"]

    # A device that loaded the draft has the attachment id but not its bytes;
    # it keeps it by reference while adding a new one.
    added = base64.b64encode(b"brand new").decode()
    response = authed_client.patch(
        _draft_url(draft_id),
        {
            "attachments": [
                {"id": kept_id},
                {"filename": "new.txt", "content_type": "text/plain", "content": added},
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    message = EmailMessage.objects.get(pk=draft_id)
    filenames = set(message.attachments.values_list("filename", flat=True))
    assert filenames == {"keep.txt", "new.txt"}
    # The kept attachment still carries its originally staged bytes.
    kept = message.attachments.get(id=kept_id)
    assert kept.metadata["pending_content_b64"] == first


def test_send_draft_promotes_in_place(
    authed_client,
    mailbox,
    sender_identity,
    requests_mock,
    django_capture_on_commit_callbacks,
):
    requests_mock.post(
        "https://api.postmarkapp.com/email",
        json={"MessageID": "pm-draft-1", "ErrorCode": 0, "Message": "OK"},
    )
    create = authed_client.post(
        DRAFT_URL,
        {
            "mailbox": str(mailbox.id),
            "to": [{"email": "customer@example.com"}],
            "subject": "Send me",
            "body_text": "hi",
        },
        format="json",
    )
    draft_id = create.data["id"]

    with django_capture_on_commit_callbacks(execute=True):
        response = authed_client.post(f"/api/mail/messages/{draft_id}/send-draft/")

    assert response.status_code == 202
    message = EmailMessage.objects.get(pk=draft_id)
    assert message.status == EmailStatus.SENT
    assert message.folder == Folder.SENT
    assert message.send_attempts.count() == 1
    # Recipient rows are materialised on send (drafts have none).
    assert message.recipients.filter(email="customer@example.com").exists()


def test_send_draft_keeps_staged_attachment(authed_client, mailbox):
    # Don't execute the on_commit send task (the test env has no S3 to
    # materialise into); just verify promote queues the draft with its staged
    # attachment intact so any device can send it.
    content = base64.b64encode(b"the attachment").decode()
    create = authed_client.post(
        DRAFT_URL,
        {
            "mailbox": str(mailbox.id),
            "to": [{"email": "customer@example.com"}],
            "subject": "Send me",
            "body_text": "hi",
            "attachments": [
                {"filename": "f.txt", "content_type": "text/plain", "content": content}
            ],
        },
        format="json",
    )
    draft_id = create.data["id"]

    response = authed_client.post(f"/api/mail/messages/{draft_id}/send-draft/")

    assert response.status_code == 202
    message = EmailMessage.objects.get(pk=draft_id)
    assert message.status == EmailStatus.QUEUED
    assert message.has_attachments is True
    assert message.attachments.get().metadata["pending_content_b64"] == content


def test_send_draft_requires_recipient(authed_client, mailbox):
    create = authed_client.post(
        DRAFT_URL,
        {"mailbox": str(mailbox.id), "subject": "no recipient", "body_text": "hi"},
        format="json",
    )
    response = authed_client.post(f"/api/mail/messages/{create.data['id']}/send-draft/")
    assert response.status_code == 400


def test_cannot_delete_non_draft(
    authed_client,
    mailbox,
    sender_identity,
    requests_mock,
    django_capture_on_commit_callbacks,
):
    requests_mock.post(
        "https://api.postmarkapp.com/email",
        json={"MessageID": "pm-1", "ErrorCode": 0, "Message": "OK"},
    )
    with django_capture_on_commit_callbacks(execute=True):
        sent = authed_client.post(
            "/api/mail/messages/send/",
            {
                "mailbox": str(mailbox.id),
                "to": [{"email": "x@example.com"}],
                "subject": "real",
                "body_text": "hi",
            },
            format="json",
        )
    message_id = sent.data["id"]

    response = authed_client.delete(f"/api/mail/messages/{message_id}/")

    assert response.status_code == 403
    assert EmailMessage.objects.filter(pk=message_id).exists()
