import django_filters
from django.db.models import Count, FilteredRelation, Max, Q
from django.utils.dateparse import parse_date
from django.utils import timezone

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
    search = django_filters.CharFilter(method="filter_search")

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
        now = timezone.now()

        # Per-user state row for each message, scoped to the requesting user.
        # LEFT JOIN, so messages without a state row keep a NULL ``_state``.
        queryset = queryset.annotate(
            _state=FilteredRelation(
                "messages__user_states",
                condition=Q(messages__user_states__user=user),
            )
        )

        if value == "starred":
            in_folder = Q(_state__is_starred=True) | (
                Q(_state__pk__isnull=True) & Q(messages__is_starred=True)
            )
        elif value == "important":
            in_folder = (
                Q(_state__is_important=True)
                | Q(messages__metadata__is_important=True)
                | Q(messages__metadata__importance__iexact="high")
                | Q(messages__raw_headers__Importance__iexact="high")
                | Q(**{"messages__raw_headers__X-Priority__startswith": "1"})
            )
        elif value == "snoozed":
            in_folder = Q(_state__snoozed_until__gt=now)
        else:
            in_folder = Q(_state__folder=value) | (
                Q(_state__pk__isnull=True) & Q(messages__folder=value)
            )
            if value == "inbox":
                in_folder &= Q(_state__snoozed_until__isnull=True) | Q(
                    _state__snoozed_until__lte=now
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

    def filter_search(self, queryset, name, value):
        term = (value or "").strip()
        if not term:
            return queryset
        query = Q()
        free_terms = []
        for token in _search_tokens(term):
            key, sep, raw = token.partition(":")
            value = raw.strip('"') if sep else token.strip('"')
            if not sep:
                free_terms.append(value)
            elif key == "from":
                query &= Q(messages__from_address__icontains=value)
            elif key == "to":
                query &= Q(messages__to_addresses__icontains=value)
            elif key == "cc":
                query &= Q(messages__cc_addresses__icontains=value)
            elif key == "bcc":
                query &= Q(messages__bcc_addresses__icontains=value)
            elif key == "subject":
                query &= Q(messages__subject__icontains=value) | Q(
                    subject__icontains=value
                )
            elif key == "label":
                query &= Q(messages__message_labels__label__name__icontains=value)
            elif key == "filename":
                query &= Q(messages__attachments__filename__icontains=value)
            elif key == "has" and value == "attachment":
                query &= Q(messages__has_attachments=True)
            elif key == "is" and value == "unread":
                query &= Q(has_unread=True) | Q(messages__is_read=False)
            elif key == "is" and value == "starred":
                query &= Q(messages__is_starred=True) | Q(
                    messages__user_states__is_starred=True
                )
            elif key == "is" and value == "important":
                query &= (
                    Q(messages__metadata__is_important=True)
                    | Q(messages__metadata__importance__iexact="high")
                    | Q(messages__user_states__is_important=True)
                )
            elif key == "after":
                date = parse_date(value)
                if date:
                    query &= Q(messages__created_at__date__gte=date)
            elif key == "before":
                date = parse_date(value)
                if date:
                    query &= Q(messages__created_at__date__lte=date)
            elif key == "in":
                query &= Q(messages__folder=value)
            else:
                free_terms.append(token)

        for free in free_terms:
            query &= (
                Q(subject__icontains=free)
                | Q(participants__icontains=free)
                | Q(messages__subject__icontains=free)
                | Q(messages__snippet__icontains=free)
                | Q(messages__body_text__icontains=free)
                | Q(messages__from_address__icontains=free)
                | Q(messages__to_addresses__icontains=free)
                | Q(messages__cc_addresses__icontains=free)
                | Q(messages__bcc_addresses__icontains=free)
                | Q(messages__attachments__filename__icontains=free)
                | Q(messages__message_labels__label__name__icontains=free)
            )
        return queryset.filter(query).distinct()


def _search_tokens(query):
    tokens = []
    current = []
    in_quotes = False
    for char in query:
        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
        elif char.isspace() and not in_quotes:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


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
        fields = ["user", "message", "folder", "is_read", "is_starred", "is_important"]


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
