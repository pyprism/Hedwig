import django_filters
from django.db.models import Count, FilteredRelation, Max, Q

from hedwig.models import (
    Contact,
    EmailAttachment,
    EmailLabel,
    EmailMessage,
    EmailMessageLabel,
    EmailMessageUserState,
    EmailRecipient,
    EmailThread,
    Mailbox,
    MailboxAlias,
    MailboxRule,
    OutboundSendAttempt,
    SenderIdentity,
    SuppressedAddress,
    UserMailboxAccess,
)


class MailboxFilter(django_filters.FilterSet):
    email = django_filters.CharFilter(method="filter_email")

    class Meta:
        model = Mailbox
        fields = [
            "domain",
            "local_part",
            "email",
            "is_active",
            "send_enabled",
            "receive_enabled",
            "is_catch_all",
        ]

    def filter_email(self, queryset, name, value):
        local_part, _, domain = value.partition("@")
        if domain:
            return queryset.filter(
                local_part__iexact=local_part, domain__name__iexact=domain
            )
        return queryset.filter(local_part__icontains=value)


class MailboxAliasFilter(django_filters.FilterSet):
    class Meta:
        model = MailboxAlias
        fields = [
            "mailbox",
            "domain",
            "local_part",
            "is_active",
            "can_send",
            "can_receive",
        ]


class SenderIdentityFilter(django_filters.FilterSet):
    class Meta:
        model = SenderIdentity
        fields = ["mailbox", "alias", "email", "is_default", "is_active"]


class UserMailboxAccessFilter(django_filters.FilterSet):
    class Meta:
        model = UserMailboxAccess
        fields = ["user", "access_type", "mailbox", "domain", "permission", "is_active"]


class EmailThreadFilter(django_filters.FilterSet):
    subject = django_filters.CharFilter(lookup_expr="icontains")
    folder = django_filters.CharFilter(method="filter_folder")

    class Meta:
        model = EmailThread
        fields = ["mailbox", "subject", "has_unread"]

    def filter_folder(self, queryset, name, value):
        """Gmail-style folder view.

        Folder is per-user, per-message state: a message's effective folder is
        the requesting user's ``EmailMessageUserState.folder`` when present, else
        the shared ``EmailMessage.folder``. A thread belongs to folder *F* when
        any of its messages resolves to *F*. The thread's count / unread / last
        timestamp are re-scoped to just the messages in that folder so each
        folder shows its own view of the conversation.
        """
        if not value:
            return queryset

        user = getattr(self.request, "user", None)

        # Per-user state row for each message, scoped to the requesting user.
        # LEFT JOIN, so messages without a state row keep a NULL ``_state``.
        queryset = queryset.annotate(
            _state=FilteredRelation(
                "messages__user_states",
                condition=Q(messages__user_states__user=user),
            )
        )

        in_folder = Q(_state__folder=value) | (
            Q(_state__pk__isnull=True) & Q(messages__folder=value)
        )
        unread_in_folder = in_folder & (
            Q(_state__is_read=False)
            | (Q(_state__pk__isnull=True) & Q(messages__is_read=False))
        )

        return (
            queryset.annotate(
                folder_message_count=Count("messages", filter=in_folder, distinct=True),
                folder_unread_count=Count(
                    "messages", filter=unread_in_folder, distinct=True
                ),
                folder_last_message_at=Max("messages__created_at", filter=in_folder),
            ).filter(folder_message_count__gt=0)
            # Aggregation drops the model's default ordering; restore a stable,
            # folder-scoped one so pagination is deterministic. OrderingFilter
            # still overrides this when ?ordering= is supplied.
            .order_by("-folder_last_message_at")
        )


class EmailMessageFilter(django_filters.FilterSet):
    subject = django_filters.CharFilter(lookup_expr="icontains")
    from_address = django_filters.CharFilter(lookup_expr="icontains")
    created_after = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="gte"
    )
    created_before = django_filters.DateTimeFilter(
        field_name="created_at", lookup_expr="lte"
    )

    class Meta:
        model = EmailMessage
        fields = [
            "mailbox",
            "thread",
            "direction",
            "status",
            "folder",
            "is_read",
            "is_starred",
            "has_attachments",
            "provider",
            "subject",
            "from_address",
            "created_after",
            "created_before",
        ]


class EmailRecipientFilter(django_filters.FilterSet):
    email = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = EmailRecipient
        fields = [
            "message",
            "recipient_type",
            "email",
            "status",
            "delivered_to_mailbox",
        ]


class EmailMessageUserStateFilter(django_filters.FilterSet):
    class Meta:
        model = EmailMessageUserState
        fields = ["user", "message", "folder", "is_read", "is_starred"]


class OutboundSendAttemptFilter(django_filters.FilterSet):
    class Meta:
        model = OutboundSendAttempt
        fields = [
            "message",
            "provider",
            "attempt_number",
            "status",
            "provider_message_id",
        ]


class EmailAttachmentFilter(django_filters.FilterSet):
    class Meta:
        model = EmailAttachment
        fields = ["message", "content_type", "is_inline", "checksum_sha256"]


class EmailLabelFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = EmailLabel
        fields = ["mailbox", "name", "color"]


class EmailMessageLabelFilter(django_filters.FilterSet):
    class Meta:
        model = EmailMessageLabel
        fields = ["message", "label"]


class MailboxRuleFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = MailboxRule
        fields = ["mailbox", "name", "priority", "is_active"]


class SuppressedAddressFilter(django_filters.FilterSet):
    email = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = SuppressedAddress
        fields = ["domain", "mailbox", "email", "reason", "source"]


class ContactFilter(django_filters.FilterSet):
    email = django_filters.CharFilter(lookup_expr="icontains")
    name = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = Contact
        fields = ["mailbox", "email", "name", "is_favorite"]
