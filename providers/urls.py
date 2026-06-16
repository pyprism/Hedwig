from django.urls import path
from rest_framework.routers import DefaultRouter

from providers.views import (
    DailyDomainSendLogViewSet,
    DeliveryEventViewSet,
    DomainDnsRecordViewSet,
    DomainViewSet,
    EmailProviderViewSet,
    PostmarkWebhookViewSet,
    ProviderWebhookViewSet,
    ProviderWebhookLogViewSet,
)


router = DefaultRouter()
router.register("email-providers", EmailProviderViewSet, basename="email-provider")
router.register("domains", DomainViewSet, basename="domain")
router.register(
    "domain-dns-records", DomainDnsRecordViewSet, basename="domain-dns-record"
)
router.register(
    "domain-send-logs", DailyDomainSendLogViewSet, basename="domain-send-log"
)
router.register(
    "provider-webhooks", ProviderWebhookLogViewSet, basename="provider-webhook"
)
router.register("delivery-events", DeliveryEventViewSet, basename="delivery-event")
router.register(
    "postmark/webhooks", PostmarkWebhookViewSet, basename="postmark-webhook"
)

urlpatterns = [
    path(
        "<str:provider_type>/webhooks/",
        ProviderWebhookViewSet.as_view({"post": "create"}),
        name="provider-type-webhook",
    ),
] + router.urls
