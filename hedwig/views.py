from django.db import transaction, connections
from django.db.models import Count, FilteredRelation, Prefetch, Q
from django.db.models.functions import Coalesce
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
    DraftEmailSerializer,
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
    # folder_last_message_at is only present when ?folder= is applied; it lets a
    # folder view sort by its own latest message rather than the global one.
    ordering_fields = [
        "last_message_at",
        "message_count",
        "created_at",
        "folder_last_message_at",
    ]

    def get_queryset(self):
        return (
            EmailThread.objects.for_api_user(self.request.user)
            .select_related("mailbox")
            .prefetch_related(
                Prefetch(
                    "messages",
                    queryset=EmailMessage.objects.for_api_user(self.request.user)
                    .order_by("-created_at")
                    .prefetch_related("attachments", "message_labels__label"),
                    to_attr="prefetched_messages",
                )
            )
        )

    @decorators.action(detail=False, methods=["get"], url_path="counts")
    def counts(self, request):
        mailbox_id = request.query_params.get("mailbox")
        messages = EmailMessage.objects.for_api_user(request.user).annotate(
            _state=FilteredRelation(
                "user_states",
                condition=Q(user_states__user=request.user),
            ),
            effective_folder=Coalesce("_state__folder", "folder"),
        )
        if mailbox_id:
            messages = messages.filter(mailbox_id=mailbox_id)

        unread = Q(_state__is_read=False) | (
            Q(_state__pk__isnull=True) & Q(is_read=False)
        )
        folder_counts = {
            row["effective_folder"]: row["unread"]
            for row in messages.values("effective_folder").annotate(
                unread=Count("id", filter=unread)
            )
        }
        label_counts = [
            {
                "id": str(row["message_labels__label"]),
                "name": row["message_labels__label__name"],
                "color": row["message_labels__label__color"],
                "unread": row["unread"],
            }
            for row in messages.filter(message_labels__label__isnull=False)
            .values(
                "message_labels__label",
                "message_labels__label__name",
                "message_labels__label__color",
            )
            .annotate(unread=Count("id", filter=unread, distinct=True))
        ]
        return response.Response({"folders": folder_counts, "labels": label_counts})


class EmailMessageViewSet(viewsets.ModelViewSet):
    serializer_class = EmailMessageSerializer
    filterset_class = EmailMessageFilter
    ordering_fields = ["created_at", "sent_at", "received_at", "subject"]
    search_fields = ["subject", "from_address", "snippet"]

    def get_permissions(self):
        if self.action in {
            "send",
            "state",
            "cancel",
            "restore",
            "permanent_delete",
            "partial_update",
            "update",
            "draft",
            "draft_update",
            "send_draft",
            # destroy is gated inside destroy(): owners may delete their own
            # drafts, everything else stays staff-only.
            "destroy",
        }:
            return [IsAuthenticated(), MustChangePasswordPermission()]
        if self.action == "create":
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

    @decorators.action(detail=False, methods=["post"], url_path="draft")
    def draft(self, request):
        """Create an unsent draft (status=draft, folder=drafts)."""
        serializer = DraftEmailSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        message = serializer.save()
        return response.Response(
            self.get_serializer(message).data, status=status.HTTP_201_CREATED
        )

    @decorators.action(detail=True, methods=["patch"], url_path="draft")
    def draft_update(self, request, pk=None):
        """Update the requesting user's own draft in place."""
        message = self._get_editable_draft()
        serializer = DraftEmailSerializer(
            message,
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        message = serializer.save()
        return response.Response(self.get_serializer(message).data)

    @decorators.action(detail=True, methods=["post"], url_path="send-draft")
    def send_draft(self, request, pk=None):
        """Promote the requesting user's own draft into a queued send, reusing
        its already-staged attachments. Sending works from any device."""
        message = self._get_editable_draft()
        if not (message.to_addresses or []):
            raise exceptions.ValidationError({"to": ["This field is required."]})
        if not (message.body_text or message.body_html):
            raise exceptions.ValidationError("Provide body_text or body_html.")

        message, attempt = EmailMessage.objects.promote_draft_to_send(message)

        def enqueue_send():
            options = {}
            if message.scheduled_at:
                options["eta"] = message.scheduled_at
            send_email_message_task.apply_async(
                args=[str(message.id), str(attempt.id)],
                **options,
            )

        transaction.on_commit(enqueue_send)
        return response.Response(
            self.get_serializer(message).data, status=status.HTTP_202_ACCEPTED
        )

    def destroy(self, request, *args, **kwargs):
        # Staff keep full delete; regular users may only delete their own draft.
        if not request.user.is_staff:
            self._get_editable_draft()
        return super().destroy(request, *args, **kwargs)

    def _get_editable_draft(self):
        """Resolve the target message and ensure it is a draft the requesting
        user authored in a mailbox they can write to."""
        message = self.get_object()
        if message.status != EmailStatus.DRAFT:
            raise exceptions.PermissionDenied("Only drafts can be edited or deleted.")
        if message.created_by_id != self.request.user.id:
            raise exceptions.PermissionDenied("You can only modify your own drafts.")
        if (
            not self.request.user.is_staff
            and not Mailbox.objects.writable_for_user(self.request.user)
            .filter(id=message.mailbox_id)
            .exists()
        ):
            raise exceptions.PermissionDenied(
                "Write access to the mailbox is required."
            )
        return message

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

    @decorators.action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        message = self.get_object()
        state, _ = EmailMessageUserState.objects.get_or_create(
            user=request.user,
            message=message,
            defaults={
                "folder": message.folder,
                "is_read": message.is_read,
                "is_starred": message.is_starred,
            },
        )
        state.folder = Folder.INBOX
        state.deleted_at = None
        state.last_seen_at = timezone.now()
        state.save(update_fields=["folder", "deleted_at", "last_seen_at", "updated_at"])
        return response.Response(EmailMessageUserStateSerializer(state).data)

    @decorators.action(detail=True, methods=["delete"], url_path="permanent-delete")
    def permanent_delete(self, request, pk=None):
        message = self.get_object()
        if not (
            request.user.is_staff
            or Mailbox.objects.writable_for_user(request.user)
            .filter(id=message.mailbox_id)
            .exists()
        ):
            raise exceptions.PermissionDenied(
                "Write access to the mailbox is required."
            )
        message.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @decorators.action(detail=True, methods=["patch"], url_path="state")
    def state(self, request, pk=None):
        """Update the requesting user's per-mailbox view of a message (read/starred/folder)."""
        message = self.get_object()
        state_data = {
            field: request.data[field]
            for field in (
                "is_read",
                "is_starred",
                "is_important",
                "folder",
                "archived_at",
                "snoozed_until",
                "deleted_at",
            )
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

        # Batched: one query to load existing states, then a single bulk_create
        # and a single bulk_update instead of a SELECT+SAVE per message (N+1).
        existing = {
            state.message_id: state
            for state in EmailMessageUserState.objects.filter(
                user=request.user, message__in=messages
            )
        }
        now = timezone.now()
        states = []
        to_create = []
        to_update = []
        for message in messages:
            state = existing.get(message.id)
            if state is None:
                state = EmailMessageUserState(
                    user=request.user,
                    message=message,
                    folder=message.folder,
                    is_read=message.is_read,
                    is_starred=message.is_starred,
                )
                to_create.append(state)
            else:
                to_update.append(state)
            for field, value in values.items():
                setattr(state, field, value)
            state.last_seen_at = now
            state.updated_at = now
            states.append(state)

        update_fields = list(values.keys()) + ["last_seen_at", "updated_at"]
        with transaction.atomic():
            if to_create:
                EmailMessageUserState.objects.bulk_create(to_create)
            if to_update:
                EmailMessageUserState.objects.bulk_update(to_update, update_fields)

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
    ordering_fields = ["updated_at", "snoozed_until", "is_important"]

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
