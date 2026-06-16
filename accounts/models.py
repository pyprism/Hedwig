from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid

from accounts.manager import UserManager


class User(AbstractUser):
    """
    Extended user model. Admin creates these accounts manually.
    Users log in to access their assigned mailboxes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=150, blank=True, null=True)
    avatar_url = models.URLField(blank=True, null=True)
    timezone = models.CharField(max_length=64, default="UTC")
    locale = models.CharField(max_length=20, default="en")
    must_change_password = models.BooleanField(
        default=True
    )  # Admin-created users may have a forced password reset on first login
    last_password_change_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.username
