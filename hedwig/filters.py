import django_filters

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

    class Meta:
        model = EmailThread
        fields = ["mailbox", "subject", "has_unread"]


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
