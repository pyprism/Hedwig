import pytest

from hedwig.models import EmailLabel, EmailMessage, EmailMessageLabel, MailboxRule
from hedwig.rules import evaluate_rules
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
