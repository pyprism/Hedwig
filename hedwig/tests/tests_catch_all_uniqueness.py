"""At most one catch-all mailbox per domain — enforced both at the DB level
(a partial unique constraint, since ``resolve_mailbox()``'s fallback just
does ``.filter(is_catch_all=True).first()``, which would be non-deterministic
if more than one existed) and with a friendly serializer validation error
instead of a raw IntegrityError.
"""

import pytest
from django.db import IntegrityError

from hedwig.models import Mailbox
from hedwig.serializers import MailboxSerializer

pytestmark = pytest.mark.django_db


def test_db_constraint_rejects_a_second_catch_all_mailbox(domain):
    Mailbox.objects.create(domain=domain, local_part="a", is_catch_all=True)
    with pytest.raises(IntegrityError):
        Mailbox.objects.create(domain=domain, local_part="b", is_catch_all=True)


def test_two_non_catch_all_mailboxes_are_fine(domain):
    Mailbox.objects.create(domain=domain, local_part="a", is_catch_all=False)
    Mailbox.objects.create(domain=domain, local_part="b", is_catch_all=False)
    assert Mailbox.objects.filter(domain=domain).count() == 2


def test_serializer_rejects_second_catch_all_with_friendly_error(domain, mailbox):
    mailbox.is_catch_all = True
    mailbox.save(update_fields=["is_catch_all"])

    serializer = MailboxSerializer(
        data={"domain": str(domain.id), "local_part": "second", "is_catch_all": True}
    )
    assert serializer.is_valid() is False
    assert "is_catch_all" in serializer.errors
    assert mailbox.email_address in str(serializer.errors["is_catch_all"][0])


def test_serializer_allows_updating_the_existing_catch_all_mailbox(domain, mailbox):
    mailbox.is_catch_all = True
    mailbox.save(update_fields=["is_catch_all"])

    serializer = MailboxSerializer(
        instance=mailbox,
        data={"display_name": "Renamed", "is_catch_all": True},
        partial=True,
    )
    assert serializer.is_valid(), serializer.errors
