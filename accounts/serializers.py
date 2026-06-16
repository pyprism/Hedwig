from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import connection, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied


User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, required=False, trim_whitespace=False
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "display_name",
            "avatar_url",
            "timezone",
            "locale",
            "must_change_password",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_password_change_at",
            "last_seen_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "last_password_change_at",
            "last_seen_at",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User.objects.create(**validated_data)
        if password:
            user.set_password(password)
            user.last_password_change_at = timezone.now()
        else:
            user.set_unusable_password()
        user.save(update_fields=["password", "last_password_change_at"])
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
            instance.last_password_change_at = timezone.now()
        instance.save()
        return instance


class CurrentUserSerializer(UserSerializer):
    class Meta(UserSerializer.Meta):
        read_only_fields = UserSerializer.Meta.read_only_fields + [
            "username",
            "email",
            "is_staff",
            "is_superuser",
            "is_active",
            "must_change_password",
            "metadata",
        ]


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.must_change_password = False
        user.last_password_change_at = timezone.now()
        user.save(
            update_fields=[
                "password",
                "must_change_password",
                "last_password_change_at",
                "updated_at",
            ]
        )
        return user


class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "display_name",
            "avatar_url",
            "timezone",
            "locale",
            "is_staff",
            "is_superuser",
            "created_at",
        ]
        read_only_fields = ["id", "is_staff", "is_superuser", "created_at"]

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_email(self, value):
        return value.strip().lower()

    def create(self, validated_data):
        password = validated_data.pop("password")
        with transaction.atomic():
            self._lock_bootstrap_check()
            is_first_user = not User.objects.exists()
            if not is_first_user and not settings.REGISTRATION_OPEN:
                raise PermissionDenied("Registration is disabled.")
            user = User.objects.create(
                **validated_data,
                is_staff=is_first_user,
                is_superuser=is_first_user,
                must_change_password=False,
                last_password_change_at=timezone.now(),
            )
            user.set_password(password)
            user.save(update_fields=["password"])
        return user

    def _lock_bootstrap_check(self):
        if connection.vendor != "postgresql":
            return
        with connection.cursor() as cursor:
            cursor.execute("LOCK TABLE accounts_user IN SHARE ROW EXCLUSIVE MODE")
