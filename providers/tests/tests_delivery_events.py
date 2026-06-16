import pytest

from hedwig.models import EmailMessage, EmailRecipient, SuppressedAddress
from providers.models import DeliveryEvent
from utils.enums import DirectionType, EmailStatus, RecipientType

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/providers/postmark/webhooks/"


@pytest.fixture
def authed_domain(domain):
    domain.webhook_secret = "test-webhook-secret"
    domain.save(update_fields=["webhook_secret"])
    return domain


@pytest.fixture
def outbound_message(mailbox, postmark_provider):
    message = EmailMessage.objects.create(
        mailbox=mailbox,
        direction=DirectionType.OUTBOUND,
        status=EmailStatus.SENT,
        from_address=mailbox.email_address,
        to_addresses=[{"email": "customer@external.com", "name": "Customer"}],
        subject="Your invoice",
        provider=postmark_provider,
        provider_message_id="pm-out-1",
    )
    EmailRecipient.objects.create(
        message=message,
        recipient_type=RecipientType.TO,
        email="customer@external.com",
        status=EmailStatus.SENT,
    )
    return message


def _delivery_payload(
    record_type,
    event_id,
    message_id="pm-out-1",
    recipient="customer@external.com",
    **extra,
):
    payload = {
        "RecordType": record_type,
        "ID": event_id,
        "MessageID": message_id,
        "Email": recipient,
        "DeliveredAt": "2026-01-01T12:00:00Z",
        "BouncedAt": "2026-01-01T12:00:00Z",
        "ReceivedAt": "2026-01-01T12:00:00Z",
        "ChangedAt": "2026-01-01T12:00:00Z",
    }
    payload.update(extra)
    return payload


def _post_webhook(api_client, payload, secret="test-webhook-secret"):
    return api_client.post(
        WEBHOOK_URL,
        payload,
        format="json",
        HTTP_X_HEDWIG_WEBHOOK_SECRET=secret,
    )


def test_delivered_event_updates_message_and_recipient(
    api_client, authed_domain, outbound_message, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _post_webhook(
            api_client, _delivery_payload("Delivery", "evt-delivered")
        )

    assert response.status_code == 200
    outbound_message.refresh_from_db()
    assert outbound_message.status == EmailStatus.DELIVERED
    recipient = outbound_message.recipients.get()
    assert recipient.status == EmailStatus.DELIVERED
    assert DeliveryEvent.objects.filter(
        message=outbound_message, event_type="delivered"
    ).exists()


def test_bounced_event_marks_failed_and_suppresses_recipient(
    api_client, authed_domain, outbound_message, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _post_webhook(api_client, _delivery_payload("Bounce", "evt-bounced"))

    assert response.status_code == 200
    outbound_message.refresh_from_db()
    assert outbound_message.status == EmailStatus.BOUNCED
    recipient = outbound_message.recipients.get()
    assert recipient.status == EmailStatus.BOUNCED

    suppressed = SuppressedAddress.objects.get(
        domain=authed_domain, email="customer@external.com"
    )
    assert suppressed.reason == "bounce"


def test_complained_event_suppresses_with_complaint_reason(
    api_client, authed_domain, outbound_message, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _post_webhook(
            api_client, _delivery_payload("SpamComplaint", "evt-complaint")
        )

    assert response.status_code == 200
    suppressed = SuppressedAddress.objects.get(
        domain=authed_domain, email="customer@external.com"
    )
    assert suppressed.reason == "complaint"


def test_unsubscribed_event_suppresses_with_unsubscribe_reason(
    api_client, authed_domain, outbound_message, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _post_webhook(
            api_client, _delivery_payload("SubscriptionChange", "evt-unsub")
        )

    assert response.status_code == 200
    suppressed = SuppressedAddress.objects.get(
        domain=authed_domain, email="customer@external.com"
    )
    assert suppressed.reason == "unsubscribe"


def test_opened_then_clicked_advances_status(
    api_client, authed_domain, outbound_message, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        _post_webhook(api_client, _delivery_payload("Delivery", "evt-1"))
    with django_capture_on_commit_callbacks(execute=True):
        _post_webhook(api_client, _delivery_payload("Open", "evt-2"))
    with django_capture_on_commit_callbacks(execute=True):
        _post_webhook(api_client, _delivery_payload("Click", "evt-3"))

    outbound_message.refresh_from_db()
    assert outbound_message.status == EmailStatus.CLICKED
    recipient = outbound_message.recipients.get()
    assert recipient.status == EmailStatus.CLICKED


def test_out_of_order_delivery_does_not_regress_status(
    api_client, authed_domain, outbound_message, django_capture_on_commit_callbacks
):
    """A late "delivered" webhook shouldn't undo an earlier "opened" status (Phase B1)."""
    with django_capture_on_commit_callbacks(execute=True):
        _post_webhook(api_client, _delivery_payload("Open", "evt-open"))
    with django_capture_on_commit_callbacks(execute=True):
        _post_webhook(api_client, _delivery_payload("Delivery", "evt-late-delivery"))

    outbound_message.refresh_from_db()
    assert outbound_message.status == EmailStatus.OPENED
    recipient = outbound_message.recipients.get()
    assert recipient.status == EmailStatus.OPENED


def test_delivery_event_for_unknown_message_is_ignored(
    api_client, authed_domain, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _post_webhook(
            api_client,
            _delivery_payload("Delivery", "evt-unknown", message_id="does-not-exist"),
        )

    assert response.status_code == 200
    assert not DeliveryEvent.objects.filter(
        provider_event_id="delivered:evt-unknown"
    ).exists()
