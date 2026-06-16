import base64

import pytest

from hedwig.models import EmailMessage, Mailbox, MailboxAlias
from providers.models import ProviderWebhookLog
from utils.enums import DirectionType

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/providers/postmark/webhooks/"


@pytest.fixture
def authed_domain(domain):
    domain.webhook_secret = "test-webhook-secret"
    domain.save(update_fields=["webhook_secret"])
    return domain


def _inbound_payload(**overrides):
    payload = {
        "FromFull": {"Email": "customer@external.com", "Name": "Customer"},
        "ToFull": [{"Email": "support@example.com", "Name": "Support"}],
        "OriginalRecipient": "support@example.com",
        "Subject": "Help needed",
        "TextBody": "I need help with my order.",
        "HtmlBody": "<p>I need help with my order.</p>",
        "MessageID": "pm-inbound-1",
        "Date": "Mon, 1 Jan 2026 12:00:00 +0000",
        "Headers": [],
        "Attachments": [],
    }
    payload.update(overrides)
    return payload


def _post_webhook(api_client, payload, secret="test-webhook-secret"):
    return api_client.post(
        WEBHOOK_URL,
        payload,
        format="json",
        HTTP_X_HEDWIG_WEBHOOK_SECRET=secret,
    )


def test_inbound_creates_message(
    api_client, authed_domain, mailbox, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _post_webhook(api_client, _inbound_payload())

    assert response.status_code == 200
    message = EmailMessage.objects.get(
        provider_message_id="pm-inbound-1", direction=DirectionType.INBOUND
    )
    assert message.mailbox_id == mailbox.id
    assert message.subject == "Help needed"
    assert message.from_address == "customer@external.com"

    log = ProviderWebhookLog.objects.get(provider_event_id="inbound:pm-inbound-1")
    assert log.status == "processed"


def test_inbound_stores_attachments(
    api_client, authed_domain, mailbox, django_capture_on_commit_callbacks
):
    content = base64.b64encode(b"hello world").decode()
    payload = _inbound_payload(
        MessageID="pm-inbound-attach",
        Attachments=[
            {
                "Name": "greeting.txt",
                "Content": content,
                "ContentType": "text/plain",
                "ContentLength": 11,
            }
        ],
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = _post_webhook(api_client, payload)

    assert response.status_code == 200
    message = EmailMessage.objects.get(provider_message_id="pm-inbound-attach")
    assert message.has_attachments is True
    attachment = message.attachments.get()
    assert attachment.filename == "greeting.txt"
    assert attachment.size_bytes == 11
    assert attachment.checksum_sha256


def test_inbound_threads_reply_with_existing_message(
    api_client, authed_domain, mailbox, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        first = _post_webhook(
            api_client,
            _inbound_payload(
                MessageID="pm-thread-1",
                Headers=[{"Name": "Message-ID", "Value": "<thread-1@external.com>"}],
            ),
        )
    assert first.status_code == 200

    with django_capture_on_commit_callbacks(execute=True):
        second = _post_webhook(
            api_client,
            _inbound_payload(
                MessageID="pm-thread-2",
                Subject="Re: Help needed",
                Headers=[
                    {"Name": "Message-ID", "Value": "<thread-2@external.com>"},
                    {"Name": "In-Reply-To", "Value": "<thread-1@external.com>"},
                ],
            ),
        )
    assert second.status_code == 200

    first_message = EmailMessage.objects.get(provider_message_id="pm-thread-1")
    second_message = EmailMessage.objects.get(provider_message_id="pm-thread-2")
    assert first_message.thread_id == second_message.thread_id


def test_inbound_falls_back_to_catch_all_mailbox(
    api_client, authed_domain, mailbox, domain, django_capture_on_commit_callbacks
):
    mailbox.is_active = False
    mailbox.save(update_fields=["is_active"])
    catch_all = Mailbox.objects.create(
        domain=domain,
        local_part="catchall",
        display_name="Catch All",
        is_catch_all=True,
        send_enabled=True,
        receive_enabled=True,
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = _post_webhook(
            api_client,
            _inbound_payload(
                MessageID="pm-catchall",
                ToFull=[{"Email": "unknown@example.com", "Name": ""}],
                OriginalRecipient="unknown@example.com",
            ),
        )

    assert response.status_code == 200
    message = EmailMessage.objects.get(provider_message_id="pm-catchall")
    assert message.mailbox_id == catch_all.id


def test_inbound_no_mailbox_match_is_ignored(
    api_client, authed_domain, mailbox, django_capture_on_commit_callbacks
):
    mailbox.is_active = False
    mailbox.save(update_fields=["is_active"])

    with django_capture_on_commit_callbacks(execute=True):
        response = _post_webhook(
            api_client,
            _inbound_payload(
                MessageID="pm-nomatch",
                ToFull=[{"Email": "unknown@example.com", "Name": ""}],
                OriginalRecipient="unknown@example.com",
            ),
        )

    assert response.status_code == 200
    assert not EmailMessage.objects.filter(provider_message_id="pm-nomatch").exists()
    log = ProviderWebhookLog.objects.get(provider_event_id="inbound:pm-nomatch")
    assert log.status == "ignored"


def test_inbound_redelivery_is_idempotent(
    api_client, authed_domain, mailbox, django_capture_on_commit_callbacks
):
    payload = _inbound_payload(MessageID="pm-dup")

    with django_capture_on_commit_callbacks(execute=True):
        first = _post_webhook(api_client, payload)
    with django_capture_on_commit_callbacks(execute=True):
        second = _post_webhook(api_client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.data["result"] == "duplicate"
    assert EmailMessage.objects.filter(provider_message_id="pm-dup").count() == 1


def test_inbound_alias_routes_to_mailbox(
    api_client, authed_domain, mailbox, domain, django_capture_on_commit_callbacks
):
    MailboxAlias.objects.create(
        mailbox=mailbox,
        domain=domain,
        local_part="help",
        display_name="Help Alias",
        can_send=False,
        can_receive=True,
        is_active=True,
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = _post_webhook(
            api_client,
            _inbound_payload(
                MessageID="pm-alias",
                ToFull=[{"Email": "help@example.com", "Name": ""}],
                OriginalRecipient="help@example.com",
            ),
        )

    assert response.status_code == 200
    message = EmailMessage.objects.get(provider_message_id="pm-alias")
    assert message.mailbox_id == mailbox.id
