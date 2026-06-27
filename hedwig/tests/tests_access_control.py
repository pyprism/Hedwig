import pytest

from hedwig.models import (
    Contact,
    EmailAttachment,
    EmailMessage,
    EmailMessageUserState,
    Mailbox,
)
from hedwig.tasks import delete_unreferenced_attachment_file_task
from utils.enums import DirectionType, EmailStatus, Folder

pytestmark = pytest.mark.django_db


def test_mailbox_list_unauthenticated_rejected(api_client, mailbox):
    response = api_client.get("/api/mail/mailboxes/")

    assert response.status_code == 401


def test_mailbox_list_staff_sees_all(api_client, staff_user, mailbox, domain):
    other_mailbox = Mailbox.objects.create(
        domain=domain,
        local_part="sales",
        display_name="Sales",
        send_enabled=True,
        receive_enabled=True,
    )
    api_client.force_authenticate(staff_user)

    response = api_client.get("/api/mail/mailboxes/")

    assert response.status_code == 200
    ids = {row["id"] for row in response.data["results"]}
    assert {str(mailbox.id), str(other_mailbox.id)} <= ids


def test_mailbox_list_regular_user_sees_only_granted(
    api_client, regular_user, mailbox, mailbox_access, domain
):
    Mailbox.objects.create(
        domain=domain,
        local_part="sales",
        display_name="Sales",
        send_enabled=True,
        receive_enabled=True,
    )
    api_client.force_authenticate(regular_user)

    response = api_client.get("/api/mail/mailboxes/")

    assert response.status_code == 200
    ids = {row["id"] for row in response.data["results"]}
    assert ids == {str(mailbox.id)}


def test_mailbox_list_estimates_storage_when_cached_usage_is_zero(
    api_client, regular_user, mailbox, mailbox_access
):
    EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=Folder.INBOX,
        from_address="customer@example.com",
        subject="Usage",
        body_text="This message should count toward storage.",
        size_bytes=0,
    )
    api_client.force_authenticate(regular_user)

    response = api_client.get("/api/mail/mailboxes/")

    assert response.status_code == 200
    assert response.data["results"][0]["used_bytes"] > 0


def test_thread_counts_respect_user_read_state(
    api_client, regular_user, mailbox, mailbox_access
):
    message = EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=Folder.INBOX,
        from_address="customer@example.com",
        subject="Unread",
        body_text="Unread message",
        is_read=False,
    )
    api_client.force_authenticate(regular_user)

    response = api_client.get("/api/mail/threads/counts/", {"mailbox": str(mailbox.id)})

    assert response.status_code == 200
    assert response.data["folders"]["inbox"] == 1

    EmailMessageUserState.objects.create(
        user=regular_user,
        message=message,
        folder=Folder.INBOX,
        is_read=True,
    )

    response = api_client.get("/api/mail/threads/counts/", {"mailbox": str(mailbox.id)})

    assert response.status_code == 200
    assert response.data["folders"]["inbox"] == 0


def test_mailbox_list_regular_user_without_access_sees_nothing(
    api_client, regular_user, mailbox
):
    api_client.force_authenticate(regular_user)

    response = api_client.get("/api/mail/mailboxes/")

    assert response.status_code == 200
    assert response.data["results"] == []


def test_mailbox_create_requires_staff(
    api_client, regular_user, mailbox_access, domain
):
    api_client.force_authenticate(regular_user)

    response = api_client.post(
        "/api/mail/mailboxes/",
        {"domain": str(domain.id), "local_part": "billing", "display_name": "Billing"},
        format="json",
    )

    assert response.status_code == 403


def test_mailbox_create_allowed_for_staff(api_client, staff_user, domain):
    api_client.force_authenticate(staff_user)

    response = api_client.post(
        "/api/mail/mailboxes/",
        {"domain": str(domain.id), "local_part": "billing", "display_name": "Billing"},
        format="json",
    )

    assert response.status_code == 201
    assert Mailbox.objects.filter(domain=domain, local_part="billing").exists()


def test_message_list_scoped_to_mailbox_access(
    api_client, regular_user, mailbox, mailbox_access, domain
):
    other_mailbox = Mailbox.objects.create(
        domain=domain,
        local_part="sales",
        display_name="Sales",
        send_enabled=True,
        receive_enabled=True,
    )
    EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=Folder.INBOX,
        from_address="customer@example.com",
        subject="Accessible",
    )
    EmailMessage.objects.create(
        mailbox=other_mailbox,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=Folder.INBOX,
        from_address="customer@example.com",
        subject="Not accessible",
    )

    api_client.force_authenticate(regular_user)
    response = api_client.get("/api/mail/messages/")

    assert response.status_code == 200
    subjects = {row["subject"] for row in response.data["results"]}
    assert subjects == {"Accessible"}


def test_page_size_query_param_controls_list_size(
    api_client, regular_user, mailbox, mailbox_access
):
    for index in range(3):
        EmailMessage.objects.create(
            mailbox=mailbox,
            direction=DirectionType.INBOUND,
            status=EmailStatus.RECEIVED,
            folder=Folder.INBOX,
            from_address="customer@example.com",
            subject=f"Message {index}",
        )
    api_client.force_authenticate(regular_user)

    response = api_client.get("/api/mail/messages/?page_size=2")

    assert response.status_code == 200
    assert len(response.data["results"]) == 2


def test_bulk_message_state_updates_scoped_messages(
    api_client, regular_user, mailbox, mailbox_access
):
    messages = [
        EmailMessage.objects.create(
            mailbox=mailbox,
            direction=DirectionType.INBOUND,
            status=EmailStatus.RECEIVED,
            folder=Folder.INBOX,
            from_address="customer@example.com",
            subject=f"Message {index}",
        )
        for index in range(2)
    ]
    api_client.force_authenticate(regular_user)

    response = api_client.post(
        "/api/mail/messages/bulk-state/",
        {"ids": [str(message.id) for message in messages], "is_read": True},
        format="json",
    )

    assert response.status_code == 200
    assert len(response.data) == 2
    assert (
        EmailMessageUserState.objects.filter(user=regular_user, is_read=True).count()
        == 2
    )


def test_message_state_create_rejects_inaccessible_message(
    api_client, regular_user, mailbox, domain
):
    other_mailbox = Mailbox.objects.create(
        domain=domain,
        local_part="sales",
        display_name="Sales",
        send_enabled=True,
        receive_enabled=True,
    )
    message = EmailMessage.objects.create(
        mailbox=other_mailbox,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=Folder.INBOX,
        from_address="customer@example.com",
        subject="Hidden",
    )
    api_client.force_authenticate(regular_user)

    response = api_client.post(
        "/api/mail/message-states/",
        {"message": str(message.id), "folder": Folder.ARCHIVE},
        format="json",
    )

    assert response.status_code == 400
    assert not EmailMessageUserState.objects.filter(message=message).exists()


def test_contact_viewset_respects_must_change_password_gate(
    api_client, regular_user, mailbox, mailbox_access
):
    Contact.objects.create(mailbox=mailbox, email="friend@example.com")
    regular_user.must_change_password = True
    regular_user.save(update_fields=["must_change_password"])
    api_client.force_authenticate(regular_user)

    response = api_client.get("/api/mail/contacts/")

    assert response.status_code == 403


def test_attachment_download_returns_presigned_url(
    api_client, regular_user, mailbox, mailbox_access, monkeypatch
):
    message = EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=Folder.INBOX,
        from_address="customer@example.com",
        subject="With attachment",
    )
    attachment = EmailAttachment.objects.create(
        message=message,
        filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=12,
        file="https://files.example.com/invoice.pdf",
    )

    class DummyUploader:
        def generate_presigned_url(self, url, expiration=3600):
            assert url == attachment.file
            assert expiration == 300
            return "https://signed.example.com/invoice.pdf"

    monkeypatch.setattr("hedwig.views.get_s3_uploader", lambda: DummyUploader())
    api_client.force_authenticate(regular_user)

    response = api_client.get(f"/api/mail/attachments/{attachment.id}/download/")

    assert response.status_code == 200
    assert response.data == {
        "url": "https://signed.example.com/invoice.pdf",
        "expires_in": 300,
    }


def test_permanent_delete_removes_attachment_file_from_s3(
    api_client,
    regular_user,
    mailbox,
    mailbox_access,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    message = EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=Folder.TRASH,
        from_address="customer@example.com",
        subject="Delete attachment",
    )
    attachment = EmailAttachment.objects.create(
        message=message,
        filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=12,
        file="https://files.example.com/email-attachments/invoice.pdf",
        storage_key="email-attachments/invoice.pdf",
    )
    deleted_urls = []

    class DummyUploader:
        def delete_file(self, url):
            deleted_urls.append(url)
            return True

    monkeypatch.setattr("hedwig.tasks.get_s3_uploader", lambda: DummyUploader())
    api_client.force_authenticate(regular_user)

    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.delete(
            f"/api/mail/messages/{message.id}/permanent-delete/"
        )

    assert response.status_code == 204
    assert deleted_urls == [attachment.file]


def test_permanent_delete_keeps_shared_attachment_file_until_last_reference(
    api_client,
    regular_user,
    mailbox,
    mailbox_access,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    first = EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=Folder.TRASH,
        from_address="customer@example.com",
        subject="Original",
    )
    second = EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.OUTBOUND,
        status=EmailStatus.SENT,
        folder=Folder.SENT,
        from_address=mailbox.email_address,
        subject="Forwarded",
    )
    file_url = "https://files.example.com/email-attachments/shared.pdf"
    storage_key = "email-attachments/shared.pdf"
    EmailAttachment.objects.create(
        message=first,
        filename="shared.pdf",
        content_type="application/pdf",
        size_bytes=12,
        file=file_url,
        storage_key=storage_key,
    )
    EmailAttachment.objects.create(
        message=second,
        filename="shared.pdf",
        content_type="application/pdf",
        size_bytes=12,
        file=file_url,
        storage_key=storage_key,
    )
    deleted_urls = []

    class DummyUploader:
        def delete_file(self, url):
            deleted_urls.append(url)
            return True

    monkeypatch.setattr("hedwig.tasks.get_s3_uploader", lambda: DummyUploader())
    api_client.force_authenticate(regular_user)

    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.delete(f"/api/mail/messages/{first.id}/permanent-delete/")

    assert response.status_code == 204
    assert deleted_urls == []

    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.delete(
            f"/api/mail/messages/{second.id}/permanent-delete/"
        )

    assert response.status_code == 204
    assert deleted_urls == [file_url]


def test_attachment_file_delete_task_skips_still_referenced_file(mailbox, monkeypatch):
    message = EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=Folder.INBOX,
        from_address="customer@example.com",
        subject="Still referenced",
    )
    file_url = "https://files.example.com/email-attachments/referenced.pdf"
    storage_key = "email-attachments/referenced.pdf"
    EmailAttachment.objects.create(
        message=message,
        filename="referenced.pdf",
        content_type="application/pdf",
        size_bytes=12,
        file=file_url,
        storage_key=storage_key,
    )
    deleted_urls = []

    class DummyUploader:
        def delete_file(self, url):
            deleted_urls.append(url)
            return True

    monkeypatch.setattr("hedwig.tasks.get_s3_uploader", lambda: DummyUploader())

    result = delete_unreferenced_attachment_file_task(file_url, storage_key)

    assert result == {"status": "skipped", "reason": "still_referenced"}
    assert deleted_urls == []
