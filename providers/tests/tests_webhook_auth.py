import pytest

from providers.models import ProviderWebhookLog

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/providers/postmark/webhooks/"
GENERIC_WEBHOOK_URL = "/api/providers/postmark/webhooks/"


def _inbound_payload(message_id="pm-auth-1"):
    return {
        "FromFull": {"Email": "customer@external.com", "Name": "Customer"},
        "ToFull": [{"Email": "support@example.com", "Name": "Support"}],
        "OriginalRecipient": "support@example.com",
        "Subject": "Help needed",
        "TextBody": "I need help.",
        "MessageID": message_id,
        "Date": "Mon, 1 Jan 2026 12:00:00 +0000",
    }


def test_valid_secret_accepted(api_client, settings, domain, mailbox):
    settings.DEBUG = False
    domain.webhook_secret = "correct-secret"
    domain.save(update_fields=["webhook_secret"])

    response = api_client.post(
        WEBHOOK_URL,
        _inbound_payload(),
        format="json",
        HTTP_X_HEDWIG_WEBHOOK_SECRET="correct-secret",
    )

    assert response.status_code == 200
    log = ProviderWebhookLog.objects.get(provider_event_id="inbound:pm-auth-1")
    assert log.signature_valid is True


def test_generic_provider_webhook_url_accepts_registered_provider(
    api_client, settings, domain, mailbox
):
    settings.DEBUG = False
    domain.webhook_secret = "correct-secret"
    domain.save(update_fields=["webhook_secret"])

    response = api_client.post(
        GENERIC_WEBHOOK_URL,
        _inbound_payload("pm-generic-auth"),
        format="json",
        HTTP_X_HEDWIG_WEBHOOK_SECRET="correct-secret",
    )

    assert response.status_code == 200
    assert ProviderWebhookLog.objects.filter(
        provider_event_id="inbound:pm-generic-auth"
    ).exists()


def test_unknown_provider_webhook_url_is_ignored(api_client):
    response = api_client.post(
        "/api/providers/mailgun/webhooks/",
        _inbound_payload("pm-unknown-provider"),
        format="json",
    )

    assert response.status_code == 200
    assert response.data["result"] == "ignored"
    log = ProviderWebhookLog.objects.get(event_type="provider_resolution_failed")
    assert log.status == "ignored"


def test_invalid_secret_rejected(api_client, settings, domain, mailbox):
    settings.DEBUG = False
    domain.webhook_secret = "correct-secret"
    domain.save(update_fields=["webhook_secret"])

    response = api_client.post(
        WEBHOOK_URL,
        _inbound_payload(),
        format="json",
        HTTP_X_HEDWIG_WEBHOOK_SECRET="wrong-secret",
    )

    assert response.status_code == 403
    assert not ProviderWebhookLog.objects.filter(
        provider_event_id="inbound:pm-auth-1"
    ).exists()


def test_missing_secret_rejected_outside_debug(api_client, settings, domain, mailbox):
    settings.DEBUG = False

    response = api_client.post(WEBHOOK_URL, _inbound_payload(), format="json")

    assert response.status_code == 403
    assert not ProviderWebhookLog.objects.filter(
        provider_event_id="inbound:pm-auth-1"
    ).exists()


def test_missing_secret_allowed_in_debug(api_client, settings, domain, mailbox):
    settings.DEBUG = True

    response = api_client.post(WEBHOOK_URL, _inbound_payload(), format="json")

    assert response.status_code == 200
    log = ProviderWebhookLog.objects.get(provider_event_id="inbound:pm-auth-1")
    assert log.signature_valid is None


def test_webhook_logs_are_staff_only(
    api_client, regular_user, staff_user, postmark_provider
):
    ProviderWebhookLog.objects.create(
        provider=postmark_provider,
        provider_event_id="raw-pii",
        event_type="inbound",
        payload={"TextBody": "private"},
    )

    api_client.force_authenticate(regular_user)
    regular_response = api_client.get("/api/providers/provider-webhooks/")
    assert regular_response.status_code == 403

    api_client.force_authenticate(staff_user)
    staff_response = api_client.get("/api/providers/provider-webhooks/")
    assert staff_response.status_code == 200
