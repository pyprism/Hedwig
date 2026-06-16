import django_filters

from providers.models import (
    DailyDomainSendLog,
    DeliveryEvent,
    Domain,
    DomainDnsRecord,
    EmailProvider,
    ProviderWebhookLog,
)


class EmailProviderFilter(django_filters.FilterSet):
    class Meta:
        model = EmailProvider
        fields = ["provider_type", "is_active", "is_sandbox"]


class DomainFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = Domain
        fields = [
            "provider",
            "status",
            "name",
            "is_active",
            "outbound_enabled",
            "inbound_enabled",
        ]


class DomainDnsRecordFilter(django_filters.FilterSet):
    class Meta:
        model = DomainDnsRecord
        fields = ["domain", "record_type", "purpose", "status"]


class DailyDomainSendLogFilter(django_filters.FilterSet):
    date_after = django_filters.DateFilter(field_name="date", lookup_expr="gte")
    date_before = django_filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = DailyDomainSendLog
        fields = ["domain", "date", "date_after", "date_before"]


class ProviderWebhookLogFilter(django_filters.FilterSet):
    received_after = django_filters.DateTimeFilter(
        field_name="received_at", lookup_expr="gte"
    )
    received_before = django_filters.DateTimeFilter(
        field_name="received_at", lookup_expr="lte"
    )

    class Meta:
        model = ProviderWebhookLog
        fields = [
            "provider",
            "domain",
            "event_type",
            "status",
            "signature_valid",
            "received_after",
            "received_before",
        ]


class DeliveryEventFilter(django_filters.FilterSet):
    occurred_after = django_filters.DateTimeFilter(
        field_name="occurred_at", lookup_expr="gte"
    )
    occurred_before = django_filters.DateTimeFilter(
        field_name="occurred_at", lookup_expr="lte"
    )

    class Meta:
        model = DeliveryEvent
        fields = [
            "message",
            "event_type",
            "recipient",
            "occurred_after",
            "occurred_before",
        ]
