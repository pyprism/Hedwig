"""Folder-aware thread listing.

Threads are not foldered server-side; folder is per-user, per-message state.
These tests prove the ``?folder=`` filter on ``/api/mail/threads/`` resolves a
thread's folder membership from the requesting user's effective message folder
(per-user ``EmailMessageUserState.folder`` overriding the shared
``EmailMessage.folder``), and re-scopes count / unread to that folder.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from hedwig.models import EmailMessage, EmailMessageUserState, EmailThread
from utils.enums import DirectionType, EmailStatus, Folder

pytestmark = pytest.mark.django_db


def _thread(mailbox, subject="Conversation"):
    return EmailThread.objects.create(mailbox=mailbox, subject=subject)


def _message(mailbox, thread, folder, *, is_read=False, subject="Hi"):
    return EmailMessage.objects.create(
        mailbox=mailbox,
        thread=thread,
        direction=DirectionType.INBOUND,
        status=EmailStatus.RECEIVED,
        folder=folder,
        is_read=is_read,
        from_address="bob@example.com",
        from_name="Bob",
        subject=subject,
        to_addresses=[{"email": mailbox.email_address, "name": ""}],
    )


def test_folder_filter_splits_threads_by_shared_message_folder(
    api_client, regular_user, mailbox, mailbox_access
):
    t_inbox = _thread(mailbox, "In inbox")
    _message(mailbox, t_inbox, Folder.INBOX)
    t_archive = _thread(mailbox, "In archive")
    _message(mailbox, t_archive, Folder.ARCHIVE)

    api_client.force_authenticate(regular_user)

    inbox = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "inbox"}
    )
    archive = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "archive"}
    )

    assert inbox.status_code == 200
    assert {r["id"] for r in inbox.data["results"]} == {str(t_inbox.id)}
    assert {r["id"] for r in archive.data["results"]} == {str(t_archive.id)}


def test_per_user_state_overrides_shared_folder(
    api_client, regular_user, mailbox, mailbox_access
):
    thread = _thread(mailbox)
    msg = _message(mailbox, thread, Folder.ARCHIVE)
    # Regular user moved this message to trash (their per-user view only).
    EmailMessageUserState.objects.create(
        user=regular_user, message=msg, folder=Folder.TRASH
    )

    api_client.force_authenticate(regular_user)

    archive = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "archive"}
    )
    trash = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "trash"}
    )

    # Shared folder is archive, but this user sees it in trash.
    assert [r["id"] for r in archive.data["results"]] == []
    assert {r["id"] for r in trash.data["results"]} == {str(thread.id)}


def test_aggregates_are_scoped_to_folder(
    api_client, regular_user, mailbox, mailbox_access
):
    thread = _thread(mailbox)
    # Two messages in inbox (one unread), one in archive (read).
    _message(mailbox, thread, Folder.INBOX, is_read=True)
    _message(mailbox, thread, Folder.INBOX, is_read=False)
    _message(mailbox, thread, Folder.ARCHIVE, is_read=True)

    api_client.force_authenticate(regular_user)

    inbox = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "inbox"}
    )
    archive = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "archive"}
    )

    inbox_row = inbox.data["results"][0]
    archive_row = archive.data["results"][0]
    assert inbox_row["message_count"] == 2
    assert inbox_row["has_unread"] is True
    assert archive_row["message_count"] == 1
    assert archive_row["has_unread"] is False


def test_thread_can_appear_in_multiple_folders(
    api_client, regular_user, mailbox, mailbox_access
):
    thread = _thread(mailbox)
    _message(mailbox, thread, Folder.INBOX)
    _message(mailbox, thread, Folder.ARCHIVE)

    api_client.force_authenticate(regular_user)

    inbox = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "inbox"}
    )
    archive = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "archive"}
    )

    assert {r["id"] for r in inbox.data["results"]} == {str(thread.id)}
    assert {r["id"] for r in archive.data["results"]} == {str(thread.id)}


def _scheduled_message(mailbox, thread, when):
    """A future-dated outbound send: folder=sent, status=queued server-side."""
    return EmailMessage.objects.create(
        mailbox=mailbox,
        thread=thread,
        direction=DirectionType.OUTBOUND,
        status=EmailStatus.QUEUED,
        folder=Folder.SENT,
        is_read=True,
        scheduled_at=when,
        from_address=mailbox.email_address,
        from_name="Me",
        subject="Later",
        to_addresses=[{"email": "bob@example.com", "name": "Bob"}],
    )


def test_scheduled_folder_lists_future_dated_sends(
    api_client, regular_user, mailbox, mailbox_access
):
    thread = _thread(mailbox, "Scheduled one")
    _scheduled_message(mailbox, thread, timezone.now() + timedelta(hours=1))

    api_client.force_authenticate(regular_user)

    scheduled = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "scheduled"}
    )

    assert scheduled.status_code == 200
    assert {r["id"] for r in scheduled.data["results"]} == {str(thread.id)}


def test_scheduled_send_hidden_from_sent_until_it_fires(
    api_client, regular_user, mailbox, mailbox_access
):
    pending = _thread(mailbox, "Still scheduled")
    _scheduled_message(mailbox, pending, timezone.now() + timedelta(hours=1))
    fired = _thread(mailbox, "Already sent")
    _scheduled_message(mailbox, fired, timezone.now() - timedelta(hours=1))

    api_client.force_authenticate(regular_user)

    sent = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "sent"}
    )

    # A past-due send stays in Sent; the still-pending one does not.
    assert {r["id"] for r in sent.data["results"]} == {str(fired.id)}


def test_trashing_a_scheduled_send_removes_it_from_scheduled(
    api_client, regular_user, mailbox, mailbox_access
):
    thread = _thread(mailbox, "Trashed before it fired")
    msg = _scheduled_message(mailbox, thread, timezone.now() + timedelta(hours=1))
    EmailMessageUserState.objects.create(
        user=regular_user, message=msg, folder=Folder.TRASH
    )

    api_client.force_authenticate(regular_user)

    scheduled = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "scheduled"}
    )
    trash = api_client.get(
        "/api/mail/threads/", {"mailbox": mailbox.id, "folder": "trash"}
    )

    assert scheduled.data["results"] == []
    assert {r["id"] for r in trash.data["results"]} == {str(thread.id)}
