from django.conf import settings
from rest_framework import decorators, permissions, response, status, viewsets

from accounts.filters import UserFilter
from accounts.models import User
from accounts.serializers import (
    CurrentUserSerializer,
    RegistrationSerializer,
    UserSerializer,
)
from utils.permissions import IsStaffOrSelf, IsStaffUser


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    filterset_class = UserFilter
    ordering_fields = ["username", "email", "created_at", "last_seen_at"]
    search_fields = ["username", "email", "display_name"]

    def get_serializer_class(self):
        if self.action == "register":
            return RegistrationSerializer
        if not self.request.user.is_staff and self.action in {
            "retrieve",
            "update",
            "partial_update",
            "me",
        }:
            return CurrentUserSerializer
        return UserSerializer

    def get_queryset(self):
        return User.objects.for_api_user(self.request.user).order_by("username")

    def get_permissions(self):
        if self.action == "register":
            return [permissions.AllowAny()]
        if self.action in {"create", "destroy"}:
            return [IsStaffUser()]
        return [IsStaffOrSelf()]

    @decorators.action(detail=False, methods=["post"], url_path="register")
    def register(self, request):
        is_first_user = not User.objects.exists()
        if not settings.REGISTRATION_OPEN and not is_first_user:
            return response.Response(
                {"detail": "Registration is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        output = UserSerializer(user, context=self.get_serializer_context())
        return response.Response(output.data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        serializer_class = self.get_serializer_class()
        if request.method == "PATCH":
            serializer = serializer_class(
                request.user,
                data=request.data,
                partial=True,
                context=self.get_serializer_context(),
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return response.Response(serializer.data)
        return response.Response(
            serializer_class(request.user, context=self.get_serializer_context()).data
        )
