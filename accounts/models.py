from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid


class User(AbstractUser):
    """
    Extended user model. Admin creates these accounts manually.
    Users log in to access their assigned mailboxes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=150, blank=True, null=True)
    must_change_password = models.BooleanField(
        default=True
    )  # Admin-created users may have a forced password reset on first login
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_user"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.username
