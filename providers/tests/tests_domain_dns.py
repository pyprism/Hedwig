import pytest

from providers.models import Domain, DomainDnsRecord
from providers.registry import get_provider
from providers.tasks import check_domain_dns_task
from utils.enums import DomainStatus

pytestmark = pytest.mark.django_db

DOMAINS_URL = "/api/providers/domains/"


def _postmark_domain_payload(**overrides):
    payload = {
        "ID": 42,
        "Name": "example.com",
        "DKIMHost": "pm._domainkey.example.com",
        "DKIMTextValue": "k=rsa; p=abc123",
        "DKIMVerified": False,
        "ReturnPathDomain": "pm-bounces.example.com",
        "ReturnPathDomainCNAMEValue": "pm.mtasv.net",
        "ReturnPathDomainVerified": False,
    }
    payload.update(overrides)
    return payload


def test_register_domain_populates_pending_dns_records(
    requests_mock, postmark_provider, domain
):
    postmark_provider.credentials["account_token"] = "acct-token"
    postmark_provider.save(update_fields=["credentials"])

    requests_mock.post(
        "https://api.postmarkapp.com/domains",
        json=_postmark_domain_payload(),
    )

    provider_impl = get_provider(postmark_provider)
    provider_impl.register_domain(domain)

    domain.refresh_from_db()
    assert domain.status == DomainStatus.PENDING
    assert domain.provider_domain_id == "42"
    assert domain.dns_checked_at is not None

    records = {r.purpose: r for r in domain.dns_record_set.all()}
    assert records["dkim"].host == "pm._domainkey.example.com"
    assert records["dkim"].status == "pending"
    assert records["return_path"].host == "pm-bounces.example.com"
    assert records["return_path"].status == "pending"


def test_check_domain_marks_verified_when_dns_passes(
    requests_mock, postmark_provider, domain
):
    postmark_provider.credentials["account_token"] = "acct-token"
    postmark_provider.save(update_fields=["credentials"])
    domain.provider_domain_id = "42"
    domain.save(update_fields=["provider_domain_id"])

    requests_mock.put(
        "https://api.postmarkapp.com/domains/42/verifydkim",
        json=_postmark_domain_payload(DKIMVerified=True),
    )
    requests_mock.put(
        "https://api.postmarkapp.com/domains/42/verifyReturnPath",
        json=_postmark_domain_payload(DKIMVerified=True, ReturnPathDomainVerified=True),
    )

    provider_impl = get_provider(postmark_provider)
    provider_impl.check_domain(domain)

    domain.refresh_from_db()
    assert domain.status == DomainStatus.VERIFIED
    assert domain.verified_at is not None
    assert all(r.status == "verified" for r in domain.dns_record_set.all())


def test_check_domain_dns_task_marks_failed_without_account_token(
    postmark_provider, domain
):
    check_domain_dns_task.delay(str(domain.id))

    domain.refresh_from_db()
    assert domain.status == DomainStatus.FAILED
    assert "account token" in domain.last_error


def test_create_domain_queues_dns_check_task(
    api_client,
    staff_user,
    postmark_provider,
    requests_mock,
    django_capture_on_commit_callbacks,
):
    postmark_provider.credentials["account_token"] = "acct-token"
    postmark_provider.save(update_fields=["credentials"])
    requests_mock.post(
        "https://api.postmarkapp.com/domains",
        json=_postmark_domain_payload(),
    )
    api_client.force_authenticate(staff_user)

    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(
            DOMAINS_URL,
            {"name": "example.com", "provider": str(postmark_provider.id)},
            format="json",
        )

    assert response.status_code == 201
    created = Domain.objects.get(pk=response.data["id"])
    assert created.status == DomainStatus.PENDING
    assert created.provider_domain_id == "42"
    assert created.dns_record_set.count() == 2


def test_check_dns_action_requires_staff(api_client, regular_user, domain):
    api_client.force_authenticate(regular_user)
    response = api_client.post(f"{DOMAINS_URL}{domain.id}/check-dns/")
    assert response.status_code == 403


def test_check_dns_action_queues_task(
    api_client,
    staff_user,
    postmark_provider,
    domain,
    requests_mock,
    django_capture_on_commit_callbacks,
):
    postmark_provider.credentials["account_token"] = "acct-token"
    postmark_provider.save(update_fields=["credentials"])
    requests_mock.post(
        "https://api.postmarkapp.com/domains",
        json=_postmark_domain_payload(),
    )
    api_client.force_authenticate(staff_user)

    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(f"{DOMAINS_URL}{domain.id}/check-dns/")

    assert response.status_code == 202
    domain.refresh_from_db()
    assert domain.provider_domain_id == "42"
    assert DomainDnsRecord.objects.filter(domain=domain).count() == 2
