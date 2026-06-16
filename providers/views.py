from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import (
    decorators,
    exceptions,
    permissions,
    response,
    status,
    throttling,
    viewsets,
)

from providers.filters import (
    DailyDomainSendLogFilter,
    DeliveryEventFilter,
    DomainDnsRecordFilter,
    DomainFilter,
    EmailProviderFilter,
    ProviderWebhookLogFilter,
)
from providers.models import (
    DailyDomainSendLog,
    DeliveryEvent,
    Domain,
    DomainDnsRecord,
    EmailProvider,
    ProviderWebhookLog,
)
from providers.registry import get_provider_class
from providers.serializers import (
    DailyDomainSendLogSerializer,
    DeliveryEventSerializer,
    DomainDnsRecordSerializer,
    DomainSerializer,
    EmailProviderSerializer,
    ProviderWebhookLogSerializer,
)
from providers.tasks import process_webhook_log_task
from utils.enums import ProviderType, ProviderWebhookStatus
from utils.permissions import IsStaffOrReadOnly, IsStaffUser


class EmailProviderViewSet(viewsets.ModelViewSet):
    serializer_class = EmailProviderSerializer
    filterset_class = EmailProviderFilter
    permission_classes = [IsStaffUser]
    ordering_fields = ["name", "provider_type", "created_at"]

    def get_queryset(self):
        return EmailProvider.objects.for_api_user(self.request.user)


class DomainViewSet(viewsets.ModelViewSet):
    serializer_class = DomainSerializer
    filterset_class = DomainFilter
    permission_classes = [IsStaffOrReadOnly]
    ordering_fields = ["name", "status", "created_at"]
    search_fields = ["name"]

    def get_queryset(self):
        return Domain.objects.for_api_user(self.request.user).select_related("provider")


class DomainDnsRecordViewSet(viewsets.ModelViewSet):
    serializer_class = DomainDnsRecordSerializer
    filterset_class = DomainDnsRecordFilter
    permission_classes = [IsStaffOrReadOnly]
    ordering_fields = ["host", "record_type", "purpose", "status"]

    def get_queryset(self):
        return DomainDnsRecord.objects.for_api_user(self.request.user).select_related(
            "domain"
        )


class DailyDomainSendLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DailyDomainSendLogSerializer
    filterset_class = DailyDomainSendLogFilter
    ordering_fields = ["date", "sent_count", "failed_count"]

    def get_queryset(self):
        return DailyDomainSendLog.objects.for_api_user(
            self.request.user
        ).select_related("domain")


class ProviderWebhookLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProviderWebhookLogSerializer
    filterset_class = ProviderWebhookLogFilter
    permission_classes = [IsStaffUser]
    ordering_fields = ["received_at", "processed_at", "status"]

    def get_queryset(self):
        return ProviderWebhookLog.objects.for_api_user(
            self.request.user
        ).select_related("provider", "domain")

    @decorators.action(detail=True, methods=["post"], url_path="process")
    def process(self, request, pk=None):
        raw_webhook = self.get_object()
        raw_webhook.status = ProviderWebhookStatus.PENDING
        raw_webhook.error_message = ""
        raw_webhook.locked_at = None
        raw_webhook.processed_at = None
        raw_webhook.save(
            update_fields=["status", "error_message", "locked_at", "processed_at"]
        )
        transaction.on_commit(
            lambda webhook_id=raw_webhook.id: process_webhook_log_task.delay(webhook_id)
        )
        return response.Response(
            {
                "id": str(raw_webhook.id),
                "status": raw_webhook.status,
                "result": "queued",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class DeliveryEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DeliveryEventSerializer
    filterset_class = DeliveryEventFilter
    permission_classes = [IsStaffUser]
    ordering_fields = ["occurred_at", "event_type"]

    def get_queryset(self):
        return DeliveryEvent.objects.for_api_user(self.request.user).select_related(
            "message", "raw_webhook"
        )


class ProviderWebhookViewSet(viewsets.ViewSet):
    """Receives provider webhooks using the registered provider implementation."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [throttling.ScopedRateThrottle]
    throttle_scope = "provider-webhook"
    provider_type = None

    def get_provider_type(self):
        return self.kwargs.get("provider_type") or self.provider_type

    def ignored_resolution_response(self, request, payload, error_message):
        raw_webhook = ProviderWebhookLog.objects.create(
            provider=None,
            domain=None,
            provider_event_id="",
            event_type="provider_resolution_failed",
            headers=dict(request.headers),
            payload=payload,
            signature_valid=None,
            status=ProviderWebhookStatus.IGNORED,
            error_message=error_message,
            processed_at=timezone.now(),
        )
        return response.Response(
            {
                "id": str(raw_webhook.id),
                "status": raw_webhook.status,
                "result": "ignored",
                "error": error_message,
            },
            status=status.HTTP_200_OK,
        )

    def create(self, request, *args, **kwargs):
        payload = request.data if isinstance(request.data, dict) else {}
        provider_type = self.get_provider_type()
        try:
            provider_cls = get_provider_class(provider_type)
        except ValueError as exc:
            return self.ignored_resolution_response(request, payload, str(exc))

        try:
            provider = provider_cls.resolve_provider_for_webhook(request, payload)
        except ObjectDoesNotExist as exc:
            return self.ignored_resolution_response(request, payload, str(exc))
        except (DjangoValidationError, ValueError) as exc:
            messages = exc.messages if hasattr(exc, "messages") else [str(exc)]
            return self.ignored_resolution_response(
                request, payload, "; ".join(messages)
            )

        provider_impl = provider_cls(provider)
        domain = provider_impl.resolve_domain(payload)
        is_valid = provider_impl.verify_webhook(request, domain)
        if is_valid is False:
            raise exceptions.PermissionDenied("Invalid webhook signature.")
        if is_valid is None and not settings.DEBUG:
            raise exceptions.PermissionDenied(
                "No webhook secret configured for this provider/domain."
            )

        kind, event_type, provider_event_id = provider_impl.classify_webhook(payload)
        headers = dict(request.headers)

        if provider_event_id:
            raw_webhook, created = ProviderWebhookLog.objects.get_or_create(
                provider=provider,
                provider_event_id=provider_event_id,
                defaults={
                    "domain": domain,
                    "event_type": event_type,
                    "headers": headers,
                    "payload": payload,
                    "signature_valid": is_valid,
                },
            )
        else:
            raw_webhook = ProviderWebhookLog.objects.create(
                provider=provider,
                domain=domain,
                provider_event_id="",
                event_type=event_type,
                headers=headers,
                payload=payload,
                signature_valid=is_valid,
            )
            created = True

        if not created:
            result = "duplicate"
        elif kind == "unknown":
            raw_webhook.status = ProviderWebhookStatus.IGNORED
            raw_webhook.error_message = f"Unrecognized event type: {event_type}"
            raw_webhook.processed_at = timezone.now()
            raw_webhook.save(update_fields=["status", "error_message", "processed_at"])
            result = "ignored"
        else:
            transaction.on_commit(
                lambda webhook_id=raw_webhook.id: process_webhook_log_task.delay(
                    webhook_id
                )
            )
            result = raw_webhook.status

        return response.Response(
            {
                "id": str(raw_webhook.id),
                "status": raw_webhook.status,
                "result": result,
            },
            status=status.HTTP_200_OK,
        )


class PostmarkWebhookViewSet(ProviderWebhookViewSet):
    """Compatibility endpoint for existing Postmark webhook URLs."""

    provider_type = ProviderType.POSTMARK
