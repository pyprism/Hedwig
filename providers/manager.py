from django.db import models, transaction
from django.db.models.functions import Greatest
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
    def reserve_send_slot(self, domain, limit):
        """Atomically check-and-increment today's ``sent_count`` for ``domain``,
        returning ``True`` iff the slot was reserved.

        A plain "read sent_count, then increment later" (the old call-site
        logic in ``providers.sending``) races: multiple sends near the daily
        cap dispatched concurrently by different Celery workers can all read
        the same stale count and all pass the check before any of them
        records. ``select_for_update`` serializes concurrent reservations for
        the same (domain, date) row; the lock is held only for this brief
        atomic block, not across the actual provider API call.
        """
        today = timezone.now().date()
        with transaction.atomic():
            log, _ = self.select_for_update().get_or_create(domain=domain, date=today)
            if limit is not None and log.sent_count >= limit:
                return False
            log.sent_count = models.F("sent_count") + 1
            log.save(update_fields=["sent_count"])
        return True

    def release_send_slot(self, domain):
        """Give back a reservation from ``reserve_send_slot`` — the send
        turned out to be a permanent failure or needs a transient-error retry,
        neither of which should count against the daily limit."""
        today = timezone.now().date()
        with transaction.atomic():
            self.select_for_update().filter(domain=domain, date=today).update(
                sent_count=Greatest(models.F("sent_count") - 1, 0)
            )


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
