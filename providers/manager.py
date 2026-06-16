from django.db import models
from django.utils import timezone

from utils.enums import ProviderType


def active_access_filter(prefix=""):
    expires_field = f"{prefix}expires_at"
    return models.Q(**{f"{prefix}is_active": True}) & (
        models.Q(**{f"{expires_field}__isnull": True})
        | models.Q(**{f"{expires_field}__gt": timezone.now()})
    )


class EmailProviderQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def postmark(self):
        return self.filter(provider_type=ProviderType.POSTMARK)

    def for_api_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_staff or user.is_superuser:
            return self.all()
        from providers.models import Domain

        return self.filter(domains__in=Domain.objects.for_api_user(user)).distinct()


class EmailProviderManager(models.Manager.from_queryset(EmailProviderQuerySet)):
    pass


class DomainQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def verified(self):
        return self.filter(status="verified")

    def inbound_enabled(self):
        return self.filter(inbound_enabled=True, is_active=True)

    def outbound_enabled(self):
        return self.filter(outbound_enabled=True, is_active=True)

    def for_api_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_staff or user.is_superuser:
            return self.all()

        access_filter = active_access_filter("user_accesses__")
        mailbox_access_filter = active_access_filter("mailboxes__user_accesses__")
        return self.filter(
            (models.Q(user_accesses__user=user) & access_filter)
            | (models.Q(mailboxes__user_accesses__user=user) & mailbox_access_filter)
        ).distinct()


class DomainManager(models.Manager.from_queryset(DomainQuerySet)):
    pass


class DomainDnsRecordQuerySet(models.QuerySet):
    def for_api_user(self, user):
        from providers.models import Domain

        return self.filter(domain__in=Domain.objects.for_api_user(user))


class DomainDnsRecordManager(models.Manager.from_queryset(DomainDnsRecordQuerySet)):
    pass


class DailyDomainSendLogQuerySet(models.QuerySet):
    def for_api_user(self, user):
        from providers.models import Domain

        return self.filter(domain__in=Domain.objects.for_api_user(user))


class DailyDomainSendLogManager(
    models.Manager.from_queryset(DailyDomainSendLogQuerySet)
):
    pass


class ProviderWebhookLogQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(status="pending")

    def for_api_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_staff or user.is_superuser:
            return self.all()
        from providers.models import Domain

        return self.filter(domain__in=Domain.objects.for_api_user(user))


class ProviderWebhookLogManager(
    models.Manager.from_queryset(ProviderWebhookLogQuerySet)
):
    pass


class DeliveryEventQuerySet(models.QuerySet):
    def for_api_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_staff or user.is_superuser:
            return self.all()
        from hedwig.models import Mailbox

        return self.filter(message__mailbox__in=Mailbox.objects.for_api_user(user))


class DeliveryEventManager(models.Manager.from_queryset(DeliveryEventQuerySet)):
    pass
