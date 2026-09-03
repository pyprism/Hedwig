"""An immediate ("send now") send is dispatched with a short countdown, not
literally instantly — giving ``POST .../cancel/`` an actual grace window
(Gmail-style "undo send") instead of the task typically already being
SENDING/SENT within moments of compose.
"""

from unittest.mock import patch

import pytest
from django.conf import settings

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


def test_immediate_send_uses_configured_undo_window(
    authed_client, mailbox, sender_identity, django_capture_on_commit_callbacks
):
    with patch(
        "hedwig.views.send_email_message_task.apply_async"
    ) as mocked_apply_async:
        with django_capture_on_commit_callbacks(execute=True):
            response = authed_client.post(
                SEND_URL, _send_payload(mailbox=str(mailbox.id)), format="json"
            )

    assert response.status_code == 202
    mocked_apply_async.assert_called_once()
    _, kwargs = mocked_apply_async.call_args
    assert kwargs["countdown"] == settings.IMMEDIATE_SEND_UNDO_WINDOW_SECONDS
    assert kwargs["countdown"] > 0
