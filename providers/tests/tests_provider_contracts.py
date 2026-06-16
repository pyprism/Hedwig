import pytest

from providers.base import BaseEmailProvider, ParsedWebhookEvent
from providers.models import ProviderWebhookLog
from providers.registry import get_provider_class, get_registered_provider_types
from utils.enums import ProviderType

pytestmark = pytest.mark.django_db


def _postmark_inbound_payload():
    return {
        "FromFull": {"Email": "customer@external.com", "Name": "Customer"},
        "ToFull": [{"Email": "support@example.com", "Name": "Support"}],
        "OriginalRecipient": "support@example.com",
        "Subject": "Help needed",
        "TextBody": "I need help.",
        "MessageID": "pm-contract-1",
        "Date": "Mon, 1 Jan 2026 12:00:00 +0000",
    }


@pytest.mark.parametrize("provider_type", get_registered_provider_types())
def test_registered_provider_implements_base_contract(provider_type):
    provider_cls = get_provider_class(provider_type)

    assert issubclass(provider_cls, BaseEmailProvider)
    assert provider_cls.provider_type == provider_type


@pytest.mark.parametrize("provider_type", get_registered_provider_types())
def test_registered_provider_classifies_and_parses_webhook(
    provider_type, postmark_provider
):
    if provider_type != ProviderType.POSTMARK:
        pytest.skip("Add a provider-specific sample payload with the provider.")

    provider_impl = get_provider_class(provider_type)(postmark_provider)
    payload = _postmark_inbound_payload()

    kind, event_type, provider_event_id = provider_impl.classify_webhook(payload)
    assert kind == "inbound"
    assert event_type == "inbound"
    assert provider_event_id == "inbound:pm-contract-1"

    raw_webhook = ProviderWebhookLog.objects.create(
        provider=postmark_provider,
        provider_event_id=provider_event_id,
        event_type=event_type,
        payload=payload,
    )

    parsed = provider_impl.parse_webhook(raw_webhook)
    assert isinstance(parsed, ParsedWebhookEvent)
    assert parsed.kind == "inbound"
    assert parsed.inbound.from_address == "customer@external.com"


@pytest.mark.parametrize("provider_type", get_registered_provider_types())
def test_registered_provider_verifies_webhook_secret(
    rf, provider_type, postmark_provider, domain
):
    if provider_type != ProviderType.POSTMARK:
        pytest.skip("Add provider-specific webhook verification coverage.")

    domain.webhook_secret = "contract-secret"
    domain.save(update_fields=["webhook_secret"])
    provider_impl = get_provider_class(provider_type)(postmark_provider)

    request = rf.post(
        "/api/providers/postmark/webhooks/",
        HTTP_X_HEDWIG_WEBHOOK_SECRET="contract-secret",
    )

    assert provider_impl.verify_webhook(request, domain) is True
    request = rf.post(
        "/api/providers/postmark/webhooks/",
        HTTP_X_HEDWIG_WEBHOOK_SECRET="wrong",
    )
    assert provider_impl.verify_webhook(request, domain) is False


@pytest.mark.parametrize("provider_type", get_registered_provider_types())
def test_registered_provider_exposes_health_check(provider_type, postmark_provider):
    provider_impl = get_provider_class(provider_type)(postmark_provider)

    assert callable(provider_impl.health_check)
