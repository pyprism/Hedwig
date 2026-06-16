from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models


class UserQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_api_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_staff or user.is_superuser:
            return self.all()
        return self.filter(pk=user.pk)

    def search(self, term):
        if not term:
            return self
        return self.filter(
            models.Q(username__icontains=term)
            | models.Q(email__icontains=term)
            | models.Q(display_name__icontains=term)
        )


class UserManager(DjangoUserManager.from_queryset(UserQuerySet)):
    pass
