from unittest.mock import patch

import pytest

from hedwig.models import EmailLabel, EmailMessage, EmailMessageLabel, MailboxRule
from hedwig.rules import MAX_FORWARD_DEPTH, _FORWARD_DEPTH_HEADER, forward_message
from hedwig.rules import _apply_actions, evaluate_rules
from hedwig.serializers import MailboxRuleSerializer
from utils.enums import DirectionType, EmailStatus, Folder

pytestmark = pytest.mark.django_db


def _message(mailbox, **overrides):
    values = {
        "mailbox": mailbox,
        "direction": DirectionType.INBOUND,
        "status": EmailStatus.RECEIVED,
        "folder": Folder.INBOX,
        "from_address": "customer@example.com",
        "to_addresses": [{"email": mailbox.email_address, "name": ""}],
        "cc_addresses": [],
        "subject": "Billing question",
        "body_text": "Hello",
    }
    values.update(overrides)
    return EmailMessage.objects.create(**values)


def test_rule_stop_prevents_later_matching_rules(mailbox):
    message = _message(mailbox)
    MailboxRule.objects.create(
        mailbox=mailbox,
        name="first",
        priority=1,
        conditions={"subject_contains": "billing"},
        actions={"add_label": "Billing", "stop": True},
    )
    MailboxRule.objects.create(
        mailbox=mailbox,
        name="second",
        priority=2,
        conditions={"subject_contains": "billing"},
        actions={"add_label": "Escalated", "move_to_folder": Folder.ARCHIVE},
    )

    evaluate_rules(mailbox, message)

    labels = {row.label.name for row in message.message_labels.select_related("label")}
    message.refresh_from_db()
    assert labels == {"Billing"}
    assert message.folder == Folder.INBOX


def test_rule_can_match_recipient_and_existing_label(mailbox):
    message = _message(mailbox, cc_addresses=[{"email": "vip@example.com"}])
    label = EmailLabel.objects.create(mailbox=mailbox, name="VIP")
    EmailMessageLabel.objects.create(message=message, label=label)
    MailboxRule.objects.create(
        mailbox=mailbox,
        name="vip-archive",
        priority=1,
        conditions={"cc_contains": "vip@", "has_label": "VIP"},
        actions={"move_to_folder": Folder.ARCHIVE},
    )

    evaluate_rules(mailbox, message)

    message.refresh_from_db()
    assert message.folder == Folder.ARCHIVE


def test_forward_refuses_to_loop_back_to_sender(mailbox):
    message = _message(mailbox, from_address="bob@example.com")

    with patch("hedwig.tasks.send_email_message_task.delay") as delay:
        result = forward_message(message, "bob@example.com")

    assert result is None
    delay.assert_not_called()
    assert not EmailMessage.objects.filter(direction=DirectionType.OUTBOUND).exists()


def test_forward_sets_incremented_depth_header(
    mailbox, django_capture_on_commit_callbacks
):
    message = _message(mailbox)

    with patch("hedwig.tasks.send_email_message_task.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            result = forward_message(message, "carol@example.com")

    assert result is not None
    assert result.raw_headers[_FORWARD_DEPTH_HEADER] == "1"
    delay.assert_called_once()


def test_rule_serializer_rejects_invalid_move_to_folder(mailbox):
    serializer = MailboxRuleSerializer(
        data={
            "mailbox": mailbox.id,
            "name": "bogus",
            "actions": {"move_to_folder": "not-a-real-folder"},
        }
    )
    assert not serializer.is_valid()
    assert "actions" in serializer.errors


def test_apply_actions_ignores_invalid_folder_on_legacy_data(mailbox):
    message = _message(mailbox)

    _apply_actions(mailbox, message, {"move_to_folder": "not-a-real-folder"})

    message.refresh_from_db()
    assert message.folder == Folder.INBOX


def test_forward_stops_once_max_depth_reached(mailbox):
    message = _message(
        mailbox, raw_headers={_FORWARD_DEPTH_HEADER: str(MAX_FORWARD_DEPTH)}
    )

    with patch("hedwig.tasks.send_email_message_task.delay") as delay:
        result = forward_message(message, "carol@example.com")

    assert result is None
    delay.assert_not_called()
    assert not EmailMessage.objects.filter(direction=DirectionType.OUTBOUND).exists()
