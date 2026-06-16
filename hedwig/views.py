from django.db import transaction, connections
from django.db.models import Prefetch
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import (
    decorators,
    exceptions,
    response,
    status,
    viewsets,
    permissions,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from hedwig.filters import (
    ContactFilter,
    EmailAttachmentFilter,
    EmailLabelFilter,
    EmailMessageFilter,
    EmailMessageLabelFilter,
    EmailMessageUserStateFilter,
    EmailRecipientFilter,
    EmailThreadFilter,
    MailboxAliasFilter,
    MailboxFilter,
    MailboxRuleFilter,
    OutboundSendAttemptFilter,
    SenderIdentityFilter,
    SuppressedAddressFilter,
    UserMailboxAccessFilter,
)
from hedwig.models import (
    Contact,
    EmailAttachment,
    EmailLabel,
    EmailMessage,
    EmailMessageLabel,
    EmailMessageUserState,
    EmailRecipient,
    EmailThread,
    Mailbox,
    MailboxAlias,
    MailboxRule,
    OutboundSendAttempt,
    SenderIdentity,
    SuppressedAddress,
    UserMailboxAccess,
)
from hedwig.serializers import (
    ContactSerializer,
    EmailAttachmentSerializer,
    EmailLabelSerializer,
    EmailMessageLabelSerializer,
    EmailMessageSerializer,
    EmailMessageUserStateSerializer,
    EmailRecipientSerializer,
    EmailThreadSerializer,
    MailboxAliasSerializer,
    MailboxRuleSerializer,
    MailboxSerializer,
    MessageStatePatchSerializer,
    OutboundSendAttemptSerializer,
    SendEmailSerializer,
    SenderIdentitySerializer,
    SuppressedAddressSerializer,
    UserMailboxAccessSerializer,
)
from hedwig.tasks import send_email_message_task
from hiren.celery import app as celery_app

from utils.s3 import get_s3_uploader
from utils.enums import DirectionType, EmailStatus, Folder, SendAttemptStatus
from utils.permissions import (
    IsStaffOrReadOnly,
    IsStaffUser,
    MustChangePasswordPermission,
)


class StaffWritableScopedModelViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStaffOrReadOnly]


class MailboxViewSet(StaffWritableScopedModelViewSet):
    serializer_class = MailboxSerializer
    filterset_class = MailboxFilter
    ordering_fields = ["local_part", "created_at", "updated_at"]
    search_fields = ["local_part", "display_name"]

    def get_queryset(self):
        return Mailbox.objects.for_api_user(self.request.user).select_related("domain")


class MailboxAliasViewSet(StaffWritableScopedModelViewSet):
    serializer_class = MailboxAliasSerializer
    filterset_class = MailboxAliasFilter
    ordering_fields = ["local_part", "created_at"]

    def get_queryset(self):
        return MailboxAlias.objects.for_api_user(self.request.user).select_related(
            "mailbox", "domain"
        )


class SenderIdentityViewSet(StaffWritableScopedModelViewSet):
    serializer_class = SenderIdentitySerializer
    filterset_class = SenderIdentityFilter
    ordering_fields = ["email", "created_at"]

    def get_queryset(self):
        return SenderIdentity.objects.for_api_user(self.request.user).select_related(
            "mailbox", "alias"
        )


class UserMailboxAccessViewSet(viewsets.ModelViewSet):
    serializer_class = UserMailboxAccessSerializer
    filterset_class = UserMailboxAccessFilter
    permission_classes = [IsStaffUser]
    ordering_fields = ["granted_at", "expires_at"]

    def get_queryset(self):
        return UserMailboxAccess.objects.for_api_user(self.request.user).select_related(
            "user", "mailbox", "domain", "granted_by"
        )

    def perform_create(self, serializer):
        serializer.save(granted_by=self.request.user)


class EmailThreadViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EmailThreadSerializer
    filterset_class = EmailThreadFilter
    ordering_fields = ["last_message_at", "message_count", "created_at"]

    def get_queryset(self):
        return EmailThread.objects.for_api_user(self.request.user).select_related(
            "mailbox"
        )


class EmailMessageViewSet(viewsets.ModelViewSet):
    serializer_class = EmailMessageSerializer
    filterset_class = EmailMessageFilter
    ordering_fields = ["created_at", "sent_at", "received_at", "subject"]
    search_fields = ["subject", "from_address", "snippet"]

    def get_permissions(self):
        if self.action in {"send", "state", "cancel", "partial_update", "update"}:
            return [IsAuthenticated(), MustChangePasswordPermission()]
        if self.action in {"create", "destroy"}:
            return [IsStaffUser()]
        return [IsAuthenticated(), MustChangePasswordPermission()]

    def get_queryset(self):
        return (
            EmailMessage.objects.for_api_user(self.request.user)
            .select_related("mailbox", "thread", "provider", "sender_identity")
            .prefetch_related(
                "recipients",
                "attachments",
                Prefetch(
                    "user_states",
                    queryset=EmailMessageUserState.objects.filter(
                        user=self.request.user
                    ),
                    to_attr="prefetched_user_state",
                ),
            )
        )

    def create(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed("POST", detail="Use /messages/send/ instead.")

    def update(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed(
            "PUT", detail="Use /messages/{id}/state/ instead."
        )

    def partial_update(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed(
            "PATCH", detail="Use /messages/{id}/state/ instead."
        )

    @decorators.action(detail=False, methods=["post"], url_path="send")
    def send(self, request):
        serializer = SendEmailSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        message = serializer.save()
        attempt = message._send_attempt

        def enqueue_send():
            options = {}
            if message.scheduled_at:
                options["eta"] = message.scheduled_at
            send_email_message_task.apply_async(
                args=[str(message.id), str(attempt.id)],
                **options,
            )

        transaction.on_commit(enqueue_send)
        output = self.get_serializer(message)
        return response.Response(output.data, status=status.HTTP_202_ACCEPTED)

    @decorators.action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        message = self.get_object()
        if (
            message.direction != DirectionType.OUTBOUND
            or message.status != EmailStatus.QUEUED
        ):
            raise exceptions.ValidationError(
                "Only queued outbound messages can be cancelled."
            )

        attempt = message.send_attempts.filter(status=SendAttemptStatus.PENDING).first()
        if attempt is None:
            raise exceptions.ValidationError("No pending send attempt to cancel.")

        attempt.status = SendAttemptStatus.CANCELLED
        attempt.finished_at = timezone.now()
        attempt.save(update_fields=["status", "finished_at"])

        message.status = EmailStatus.CANCELLED
        message.folder = Folder.DRAFTS
        message.save(update_fields=["status", "folder", "updated_at"])

        return response.Response(self.get_serializer(message).data)

    @decorators.action(detail=True, methods=["patch"], url_path="state")
    def state(self, request, pk=None):
        """Update the requesting user's per-mailbox view of a message (read/starred/folder)."""
        message = self.get_object()
        state_data = {
            field: request.data[field]
            for field in ("is_read", "is_starred", "folder")
            if field in request.data
        }
        serializer = MessageStatePatchSerializer(data=state_data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data

        state = EmailMessageUserState.objects.filter(
            user=request.user, message=message
        ).first()
        if state is None:
            state = EmailMessageUserState(
                user=request.user,
                message=message,
                folder=message.folder,
                is_read=message.is_read,
                is_starred=message.is_starred,
            )
        for field, value in values.items():
            setattr(state, field, value)
        state.last_seen_at = timezone.now()
        state.save()
        return response.Response(EmailMessageUserStateSerializer(state).data)

    @decorators.action(detail=False, methods=["post"], url_path="bulk-state")
    def bulk_state(self, request):
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not ids:
            raise exceptions.ValidationError(
                {"ids": ["Provide a non-empty list of message ids."]}
            )

        serializer = MessageStatePatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if not values:
            raise exceptions.ValidationError(
                "Provide at least one state field to update."
            )

        messages = list(self.get_queryset().filter(id__in=ids))
        if len(messages) != len(set(ids)):
            raise exceptions.NotFound("One or more messages were not found.")

        states = []
        now = timezone.now()
        for message in messages:
            state = EmailMessageUserState.objects.filter(
                user=request.user, message=message
            ).first()
            if state is None:
                state = EmailMessageUserState(
                    user=request.user,
                    message=message,
                    folder=message.folder,
                    is_read=message.is_read,
                    is_starred=message.is_starred,
                )
            for field, value in values.items():
                setattr(state, field, value)
            state.last_seen_at = now
            state.save()
            states.append(state)

        output = EmailMessageUserStateSerializer(
            states, many=True, context=self.get_serializer_context()
        )
        return response.Response(output.data)


class EmailRecipientViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EmailRecipientSerializer
    filterset_class = EmailRecipientFilter
    ordering_fields = ["email", "recipient_type", "created_at"]

    def get_queryset(self):
        return EmailRecipient.objects.for_api_user(self.request.user).select_related(
            "message", "delivered_to_mailbox"
        )


class EmailMessageUserStateViewSet(viewsets.ModelViewSet):
    serializer_class = EmailMessageUserStateSerializer
    filterset_class = EmailMessageUserStateFilter
    ordering_fields = ["updated_at", "snoozed_until"]

    def get_queryset(self):
        return EmailMessageUserState.objects.for_api_user(
            self.request.user
        ).select_related("user", "message")

    def perform_create(self, serializer):
        if not self.request.user.is_staff:
            serializer.save(user=self.request.user)
        else:
            serializer.save()


class OutboundSendAttemptViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OutboundSendAttemptSerializer
    filterset_class = OutboundSendAttemptFilter
    ordering_fields = ["created_at", "attempt_number", "status"]

    def get_queryset(self):
        return OutboundSendAttempt.objects.for_api_user(
            self.request.user
        ).select_related("message", "provider")


class EmailAttachmentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EmailAttachmentSerializer
    filterset_class = EmailAttachmentFilter
    ordering_fields = ["filename", "size_bytes", "created_at"]

    def get_queryset(self):
        return EmailAttachment.objects.for_api_user(self.request.user).select_related(
            "message"
        )

    @decorators.action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        attachment = self.get_object()
        if not attachment.file:
            raise exceptions.NotFound("Attachment file is not available.")

        expires_in = 300
        url = get_s3_uploader().generate_presigned_url(
            attachment.file, expiration=expires_in
        )
        if not url:
            raise exceptions.APIException("Could not generate attachment download URL.")
        return response.Response({"url": url, "expires_in": expires_in})


class EmailLabelViewSet(StaffWritableScopedModelViewSet):
    serializer_class = EmailLabelSerializer
    filterset_class = EmailLabelFilter
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        return EmailLabel.objects.for_api_user(self.request.user).select_related(
            "mailbox"
        )


class EmailMessageLabelViewSet(StaffWritableScopedModelViewSet):
    serializer_class = EmailMessageLabelSerializer
    filterset_class = EmailMessageLabelFilter
    ordering_fields = ["added_at"]

    def get_queryset(self):
        return EmailMessageLabel.objects.for_api_user(self.request.user).select_related(
            "message", "label"
        )


class MailboxRuleViewSet(StaffWritableScopedModelViewSet):
    serializer_class = MailboxRuleSerializer
    filterset_class = MailboxRuleFilter
    ordering_fields = ["priority", "name", "created_at"]

    def get_queryset(self):
        return MailboxRule.objects.for_api_user(self.request.user).select_related(
            "mailbox", "created_by"
        )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class SuppressedAddressViewSet(StaffWritableScopedModelViewSet):
    serializer_class = SuppressedAddressSerializer
    filterset_class = SuppressedAddressFilter
    ordering_fields = ["email", "created_at", "expires_at"]

    def get_queryset(self):
        return SuppressedAddress.objects.for_api_user(self.request.user).select_related(
            "domain", "mailbox", "raw_event"
        )


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    filterset_class = ContactFilter
    permission_classes = [IsAuthenticated, MustChangePasswordPermission]
    ordering_fields = ["last_contacted_at", "times_contacted", "name", "created_at"]
    search_fields = ["name", "email"]

    def get_queryset(self):
        return Contact.objects.for_api_user(self.request.user).select_related("mailbox")


# debug only views
class HealthView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        checks = {"database": self._database_ok(), "broker": self._broker_ok()}
        healthy = all(checks.values())
        return response.Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=(
                status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
        )

    def _database_ok(self):
        try:
            connections["default"].ensure_connection()
            return True
        except Exception:
            return False

    def _broker_ok(self):
        try:
            with celery_app.connection_for_read() as connection:
                connection.ensure_connection(max_retries=1)
            return True
        except Exception:
            return False


def swagger_ui(request):
    return HttpResponse(
        """<!doctype html>
<html>
  <head>
    <title>Hedwig API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist/swagger-ui.css">
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist/swagger-ui-bundle.js"></script>
    <script>
      window.ui = SwaggerUIBundle({url: "/api/schema/", dom_id: "#swagger-ui"});
    </script>
  </body>
</html>
""",
        content_type="text/html",
    )
