from rest_framework import serializers

from providers.models import (
    DailyDomainSendLog,
    DeliveryEvent,
    Domain,
    DomainDnsRecord,
    EmailProvider,
    ProviderWebhookLog,
)
from providers.registry import is_registered_provider_type
from utils.enums import ProviderType


class EmailProviderSerializer(serializers.ModelSerializer):
    credentials = serializers.JSONField(write_only=True, required=False)
    has_credentials = serializers.SerializerMethodField()

    class Meta:
        model = EmailProvider
        fields = [
            "id",
            "name",
            "provider_type",
            "provider_account_id",
            "region",
            "api_base_url",
            "credentials",
            "credential_reference",
            "has_credentials",
            "webhook_signing_secret",
            "capabilities",
            "default_from_email",
            "max_send_per_day",
            "is_sandbox",
            "last_health_check_at",
            "last_health_check_error",
            "metadata",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "has_credentials", "created_at", "updated_at"]
        extra_kwargs = {
            "webhook_signing_secret": {"write_only": True, "required": False},
        }

    def get_has_credentials(self, obj):
        return bool(obj.credentials or obj.credential_reference)

    def validate_provider_type(self, value):
        if not is_registered_provider_type(value):
            raise serializers.ValidationError(
                f"No provider implementation is registered for '{value}'."
            )
        return value

    def validate(self, attrs):
        provider_type = attrs.get(
            "provider_type", getattr(self.instance, "provider_type", None)
        )
        credentials = attrs.get(
            "credentials", getattr(self.instance, "credentials", None) or {}
        )
        if (
            provider_type == ProviderType.POSTMARK
            and credentials
            and not any(key in credentials for key in ("server_token", "api_token"))
        ):
            raise serializers.ValidationError(
                {
                    "credentials": [
                        "Postmark credentials must include server_token or api_token."
                    ]
                }
            )
        return attrs


class DomainDnsRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DomainDnsRecord
        fields = [
            "id",
            "domain",
            "record_type",
            "host",
            "value",
            "priority",
            "ttl",
            "purpose",
            "status",
            "last_checked_at",
            "last_error",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class DomainSerializer(serializers.ModelSerializer):
    dns_record_set = DomainDnsRecordSerializer(many=True, read_only=True)

    class Meta:
        model = Domain
        fields = [
            "id",
            "name",
            "provider",
            "status",
            "provider_domain_id",
            "outbound_enabled",
            "inbound_enabled",
            "tracking_enabled",
            "return_path_domain",
            "tracking_domain",
            "verification_token",
            "dns_records",
            "dns_record_set",
            "inbound_route",
            "webhook_secret",
            "max_send_per_day",
            "is_active",
            "verified_at",
            "dns_checked_at",
            "last_error",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "verified_at",
            "dns_checked_at",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "webhook_secret": {"write_only": True, "required": False},
            "verification_token": {"write_only": True, "required": False},
        }

    def validate_name(self, value):
        value = value.strip().lower()
        if "@" in value or "/" in value:
            raise serializers.ValidationError("Use a bare domain like example.com.")
        return value


class DailyDomainSendLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyDomainSendLog
        fields = ["id", "domain", "date", "sent_count", "failed_count"]
        read_only_fields = ["id"]


class ProviderWebhookLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderWebhookLog
        fields = [
            "id",
            "provider",
            "domain",
            "provider_event_id",
            "event_type",
            "headers",
            "payload",
            "status",
            "signature_valid",
            "error_message",
            "attempt_count",
            "received_at",
            "locked_at",
            "processed_at",
        ]
        read_only_fields = ["id", "received_at", "locked_at", "processed_at"]


class DeliveryEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryEvent
        fields = [
            "id",
            "message",
            "event_type",
            "provider_event_id",
            "reason",
            "link_url",
            "recipient",
            "occurred_at",
            "metadata",
            "raw_webhook",
        ]
        read_only_fields = ["id"]
