import pytest
import base64

from hedwig.models import EmailMessage, EmailAttachment, SuppressedAddress
from providers.postmark import TransientSendError
from providers.sending import materialize_attachments
from providers.models import DailyDomainSendLog
from utils.enums import EmailStatus, SendAttemptStatus

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
def authed_client(api_client, regular_user, mailbox_access):
    api_client.force_authenticate(regular_user)
    return api_client


def test_send_email_success(
    authed_client,
    mailbox,
    sender_identity,
    requests_mock,
    django_capture_on_commit_callbacks,
):
    requests_mock.post(
        "https://api.postmarkapp.com/email",
        json={"MessageID": "postmark-msg-1", "ErrorCode": 0, "Message": "OK"},
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = authed_client.post(
            SEND_URL,
            _send_payload(mailbox=str(mailbox.id)),
            format="json",
        )

    assert response.status_code == 202
    message = EmailMessage.objects.get(pk=response.data["id"])
    assert message.status == EmailStatus.SENT
    assert message.provider_message_id == "postmark-msg-1"
    assert message.rfc_message_id.startswith("<") and message.rfc_message_id.endswith(
        f"@{mailbox.domain.name}>"
    )

    attempt = message.send_attempts.get()
    assert attempt.status == SendAttemptStatus.SENT

    sent_headers = {
        item["Name"]: item["Value"]
        for item in requests_mock.last_request.json().get("Headers", [])
    }
    assert sent_headers["Message-ID"] == message.rfc_message_id


def test_send_email_reply_includes_threading_headers(
    authed_client,
    mailbox,
    sender_identity,
    requests_mock,
    django_capture_on_commit_callbacks,
):
    requests_mock.post(
        "https://api.postmarkapp.com/email",
        json={"MessageID": "postmark-msg-2", "ErrorCode": 0, "Message": "OK"},
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = authed_client.post(
            SEND_URL,
            _send_payload(
                mailbox=str(mailbox.id),
                in_reply_to="<original@example.com>",
            ),
            format="json",
        )

    assert response.status_code == 202
    sent_headers = {
        item["Name"]: item["Value"]
        for item in requests_mock.last_request.json().get("Headers", [])
    }
    assert sent_headers["In-Reply-To"] == "<original@example.com>"


def test_send_email_too_many_recipients(authed_client, mailbox, sender_identity):
    response = authed_client.post(
        SEND_URL,
        _send_payload(
            mailbox=str(mailbox.id),
            to=[{"email": f"user{i}@example.com"} for i in range(51)],
        ),
        format="json",
    )

    assert response.status_code == 400


def test_send_email_uses_provider_recipient_limit(
    authed_client, mailbox, sender_identity, postmark_provider
):
    postmark_provider.capabilities = {"max_recipients_per_message": 2}
    postmark_provider.save(update_fields=["capabilities"])

    response = authed_client.post(
        SEND_URL,
        _send_payload(
            mailbox=str(mailbox.id),
            to=[
                {"email": "a@example.com"},
                {"email": "b@example.com"},
                {"email": "c@example.com"},
            ],
        ),
        format="json",
    )

    assert response.status_code == 400
    assert "This provider allows at most 2 recipients" in str(response.data)


def test_send_email_rejects_dual_recipient_field_names(
    authed_client, mailbox, sender_identity
):
    response = authed_client.post(
        SEND_URL,
        _send_payload(
            mailbox=str(mailbox.id),
            to=[{"email": "customer@example.com"}],
            to_addresses=[{"email": "alias@example.com"}],
        ),
        format="json",
    )

    assert response.status_code == 400
    assert "Use 'to' or 'to_addresses'" in str(response.data)


def test_send_email_response_hides_pending_attachment_content(
    authed_client,
    mailbox,
    sender_identity,
    requests_mock,
    django_capture_on_commit_callbacks,
    monkeypatch,
):
    monkeypatch.setattr(
        "providers.sending.store_attachment_content",
        lambda *args, **kwargs: (
            "https://storage.example/secret.txt",
            "email-attachments/secret.txt",
            "checksum",
            len(b"secret file bytes"),
        ),
    )
    requests_mock.post(
        "https://api.postmarkapp.com/email",
        json={"MessageID": "postmark-msg-attachment", "ErrorCode": 0, "Message": "OK"},
    )
    content = base64.b64encode(b"secret file bytes").decode()

    with django_capture_on_commit_callbacks(execute=True):
        response = authed_client.post(
            SEND_URL,
            _send_payload(
                mailbox=str(mailbox.id),
                attachments=[
                    {
                        "filename": "secret.txt",
                        "content_type": "text/plain",
                        "content": content,
                    }
                ],
            ),
            format="json",
        )

    assert response.status_code == 202
    attachment = EmailAttachment.objects.get(message_id=response.data["id"])
    assert attachment.filename == "secret.txt"
    assert "pending_content_b64" not in response.data["attachments"][0]["metadata"]


def test_materialize_attachments_retains_pending_content_when_storage_fails(
    mailbox, sender_identity, regular_user, monkeypatch
):
    content = base64.b64encode(b"secret file bytes").decode()
    message, _ = EmailMessage.objects.create_outbound_message(
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
        materialize_attachments(message)

    attachment = message.attachments.get()
    assert not attachment.file
    assert not attachment.storage_key
    assert attachment.checksum_sha256 in ("", None)
    assert attachment.metadata["pending_content_b64"] == content


def test_send_email_requires_body(authed_client, mailbox, sender_identity):
    payload = _send_payload(mailbox=str(mailbox.id))
    payload.pop("body_text")

    response = authed_client.post(SEND_URL, payload, format="json")

    assert response.status_code == 400


def test_send_email_sender_identity_must_match_mailbox(
    authed_client, mailbox, sender_identity, domain
):
    from hedwig.models import Mailbox, SenderIdentity

    other_mailbox = Mailbox.objects.create(
        domain=domain,
        local_part="sales",
        display_name="Sales",
        send_enabled=True,
        receive_enabled=True,
    )
    other_identity = SenderIdentity.objects.create(
        mailbox=other_mailbox,
        email=other_mailbox.email_address,
        display_name="Sales Team",
        is_default=True,
        is_active=True,
    )

    response = authed_client.post(
        SEND_URL,
        _send_payload(mailbox=str(mailbox.id), sender_identity=str(other_identity.id)),
        format="json",
    )

    assert response.status_code == 400


def test_send_email_suppressed_recipient_rejected(
    authed_client, mailbox, sender_identity
):
    SuppressedAddress.objects.create(
        domain=mailbox.domain,
        email="customer@example.com",
        reason="bounce",
        source="webhook",
    )

    response = authed_client.post(
        SEND_URL,
        _send_payload(mailbox=str(mailbox.id)),
        format="json",
    )

    assert response.status_code == 400


def test_send_email_scheduled_does_not_dispatch_immediately(
    authed_client,
    mailbox,
    sender_identity,
    requests_mock,
    django_capture_on_commit_callbacks,
):
    from datetime import timedelta
    from unittest.mock import patch

    from django.utils import timezone

    requests_mock.post(
        "https://api.postmarkapp.com/email",
        json={"MessageID": "postmark-msg-3", "ErrorCode": 0, "Message": "OK"},
    )

    scheduled_at = timezone.now() + timedelta(hours=1)

    with patch("hedwig.views.send_email_message_task.apply_async") as apply_async:
        with django_capture_on_commit_callbacks(execute=True):
            response = authed_client.post(
                SEND_URL,
                _send_payload(
                    mailbox=str(mailbox.id), scheduled_at=scheduled_at.isoformat()
                ),
                format="json",
            )

    assert response.status_code == 202
    assert not requests_mock.called
    message = EmailMessage.objects.get(pk=response.data["id"])
    assert message.status == EmailStatus.QUEUED

    apply_async.assert_called_once()
    assert apply_async.call_args.kwargs["eta"] == scheduled_at


def test_send_email_postmark_error_marks_attempt_failed(
    authed_client,
    mailbox,
    sender_identity,
    requests_mock,
    django_capture_on_commit_callbacks,
):
    requests_mock.post(
        "https://api.postmarkapp.com/email",
        status_code=422,
        json={"ErrorCode": 300, "Message": "Invalid 'From' address."},
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = authed_client.post(
            SEND_URL,
            _send_payload(mailbox=str(mailbox.id)),
            format="json",
        )

    assert response.status_code == 202
    message = EmailMessage.objects.get(pk=response.data["id"])
    assert message.status == EmailStatus.FAILED

    attempt = message.send_attempts.get()
    assert attempt.status == SendAttemptStatus.FAILED


def test_send_email_daily_limit_exceeded(
    authed_client,
    mailbox,
    sender_identity,
    domain,
    requests_mock,
    django_capture_on_commit_callbacks,
):
    from django.utils import timezone

    domain.max_send_per_day = 1
    domain.save(update_fields=["max_send_per_day"])
    DailyDomainSendLog.objects.create(
        domain=domain, date=timezone.now().date(), sent_count=1
    )

    requests_mock.post(
        "https://api.postmarkapp.com/email",
        json={"MessageID": "postmark-msg-4", "ErrorCode": 0, "Message": "OK"},
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = authed_client.post(
            SEND_URL,
            _send_payload(mailbox=str(mailbox.id)),
            format="json",
        )

    assert response.status_code == 202
    assert not requests_mock.called
    message = EmailMessage.objects.get(pk=response.data["id"])
    assert message.status == EmailStatus.FAILED

    attempt = message.send_attempts.get()
    assert attempt.error_code == "validation_error"

    log = DailyDomainSendLog.objects.get(domain=domain, date=timezone.now().date())
    assert log.failed_count == 1
    assert log.sent_count == 1
