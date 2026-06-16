"""
Root pytest conftest.

- Forces Celery to run tasks synchronously (CELERY_TASK_ALWAYS_EAGER) so tests
  never need a live RabbitMQ broker.
- Provides shared fixtures for the access-control / outbound / inbound test
  suites: users, an active Postmark provider+domain+mailbox, and a DRF
  APIClient.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from hedwig.models import Mailbox, SenderIdentity, UserMailboxAccess
from providers.models import Domain, EmailProvider
from utils.enums import AccessType, MailboxPermissionType, ProviderType


@pytest.fixture(autouse=True)
def celery_eager_mode(settings):
    """Make every Celery task execute synchronously & ignore failures."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = False


@pytest.fixture(autouse=True)
def disable_s3_uploads(settings):
    """Ensure attachment storage gracefully no-ops in tests.

    ``.env``'s AWS values are placeholders (e.g. ``your-s3-endpoint-url``),
    which boto3 rejects outright when building a client. Clearing them makes
    ``utils.s3.S3ImageUploader`` fall back to its "bucket not configured"
    no-op path instead of erroring.
    """
    settings.AWS_STORAGE_BUCKET_NAME = None
    settings.AWS_S3_ENDPOINT_URL = None
    settings.AWS_S3_CUSTOM_DOMAIN = None


@pytest.fixture(autouse=True)
def disable_debug_toolbar(settings):
    """Strip the debug toolbar middleware.

    pytest-django forces ``settings.DEBUG = False`` before the urlconf is
    first imported, so the ``djdt`` namespace never gets registered even when
    ``debug=true`` is set in the environment. The toolbar middleware (with
    this project's ``SHOW_TOOLBAR_CALLBACK: lambda request: True``) would
    still try to render it and crash with ``NoReverseMatch``.
    """
    settings.MIDDLEWARE = [
        mw
        for mw in settings.MIDDLEWARE
        if mw != "debug_toolbar.middleware.DebugToolbarMiddleware"
    ]


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staff",
        email="staff@example.com",
        password="staffpass123",
        is_staff=True,
        must_change_password=False,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="regular",
        email="regular@example.com",
        password="regularpass123",
        must_change_password=False,
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        username="other",
        email="other@example.com",
        password="otherpass123",
        must_change_password=False,
    )


@pytest.fixture
def postmark_provider(db):
    return EmailProvider.objects.create(
        name="Postmark Test",
        provider_type=ProviderType.POSTMARK,
        credentials={"server_token": "test-server-token"},
        default_from_email="noreply@example.com",
        is_active=True,
    )


@pytest.fixture
def domain(postmark_provider):
    return Domain.objects.create(
        name="example.com",
        provider=postmark_provider,
        outbound_enabled=True,
        inbound_enabled=True,
        is_active=True,
    )


@pytest.fixture
def mailbox(domain):
    return Mailbox.objects.create(
        domain=domain,
        local_part="support",
        display_name="Support",
        send_enabled=True,
        receive_enabled=True,
    )


@pytest.fixture
def sender_identity(mailbox):
    return SenderIdentity.objects.create(
        mailbox=mailbox,
        email=mailbox.email_address,
        display_name="Support Team",
        is_default=True,
        is_active=True,
    )


@pytest.fixture
def mailbox_access(regular_user, mailbox):
    return UserMailboxAccess.objects.create(
        user=regular_user,
        access_type=AccessType.MAILBOX,
        mailbox=mailbox,
        permission=MailboxPermissionType.READ_WRITE,
    )
