import base64
import binascii

from rest_framework import serializers

from hedwig.rules import SUPPORTED_ACTIONS, SUPPORTED_CONDITIONS
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
from utils.enums import AccessType


def normalize_address_rows(rows):
    rows = rows or []
    email_field = serializers.EmailField()
    normalized = []
    for row in rows:
        if isinstance(row, str):
            row = {"email": row}
        if not isinstance(row, dict):
            raise serializers.ValidationError("Recipients must be emails or objects.")
        email = email_field.run_validation(row.get("email", ""))
        normalized.append({"email": email.lower(), "name": row.get("name", "")})
    return normalized


class MailboxSerializer(serializers.ModelSerializer):
    email_address = serializers.CharField(read_only=True)

    class Meta:
        model = Mailbox
        fields = [
            "id",
            "domain",
            "local_part",
            "email_address",
            "display_name",
            "is_catch_all",
            "forward_to",
            "reply_to",
            "send_enabled",
            "receive_enabled",
            "quota_bytes",
            "used_bytes",
            "signature_html",
            "signature_text",
            "provider_sender_id",
            "metadata",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "email_address",
            "used_bytes",
            "created_at",
            "updated_at",
        ]

    def validate_local_part(self, value):
        return value.strip().lower()


class MailboxAliasSerializer(serializers.ModelSerializer):
    email_address = serializers.CharField(read_only=True)

    class Meta:
        model = MailboxAlias
        fields = [
            "id",
            "mailbox",
            "domain",
            "local_part",
            "email_address",
            "display_name",
            "can_send",
            "can_receive",
            "is_active",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "email_address", "created_at", "updated_at"]

    def validate_local_part(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        mailbox = attrs.get("mailbox", getattr(self.instance, "mailbox", None))
        domain = attrs.get("domain", getattr(self.instance, "domain", None))
        local_part = attrs.get("local_part", getattr(self.instance, "local_part", None))

        if mailbox and domain and mailbox.domain_id != domain.id:
            raise serializers.ValidationError(
                {"domain": ["Alias domain must match the mailbox domain."]}
            )
        if domain and local_part:
            conflict = Mailbox.objects.filter(
                domain=domain, local_part__iexact=local_part
            )
            if conflict.exists():
                raise serializers.ValidationError(
                    {
                        "local_part": [
                            "Alias conflicts with an existing mailbox address."
                        ]
                    }
                )
        return attrs


class SenderIdentitySerializer(serializers.ModelSerializer):
    class Meta:
        model = SenderIdentity
        fields = [
            "id",
            "mailbox",
            "alias",
            "email",
            "display_name",
            "reply_to",
            "signature_html",
            "signature_text",
            "is_default",
            "is_active",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        mailbox = attrs.get("mailbox", getattr(self.instance, "mailbox", None))
        alias = attrs.get("alias", getattr(self.instance, "alias", None))
        if alias and mailbox and alias.mailbox_id != mailbox.id:
            raise serializers.ValidationError(
                {"alias": ["Sender identity alias must belong to the mailbox."]}
            )
        return attrs


class UserMailboxAccessSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserMailboxAccess
        fields = [
            "id",
            "user",
            "access_type",
            "mailbox",
            "domain",
            "permission",
            "granted_by",
            "granted_at",
            "expires_at",
            "is_active",
        ]
        read_only_fields = ["id", "granted_by", "granted_at"]

    def validate(self, attrs):
        access_type = attrs.get(
            "access_type", getattr(self.instance, "access_type", None)
        )
        mailbox = attrs.get("mailbox", getattr(self.instance, "mailbox", None))
        domain = attrs.get("domain", getattr(self.instance, "domain", None))

        if access_type == AccessType.MAILBOX and (
            mailbox is None or domain is not None
        ):
            raise serializers.ValidationError(
                "Mailbox access must target exactly one mailbox (and no domain)."
            )
        if access_type == AccessType.DOMAIN and (domain is None or mailbox is not None):
            raise serializers.ValidationError(
                "Domain access must target exactly one domain (and no mailbox)."
            )
        return attrs


class EmailAttachmentSerializer(serializers.ModelSerializer):
    metadata = serializers.SerializerMethodField()

    def get_metadata(self, obj):
        metadata = dict(obj.metadata or {})
        metadata.pop("pending_content_b64", None)
        return metadata

    class Meta:
        model = EmailAttachment
        fields = [
            "id",
            "message",
            "filename",
            "content_type",
            "size_bytes",
            "file",
            "storage_key",
            "checksum_sha256",
            "content_id",
            "content_disposition",
            "is_inline",
            "metadata",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class EmailRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailRecipient
        fields = [
            "id",
            "message",
            "recipient_type",
            "email",
            "name",
            "delivered_to_mailbox",
            "provider_recipient_id",
            "status",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class EmailThreadSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailThread
        fields = [
            "id",
            "mailbox",
            "subject",
            "normalized_subject",
            "root_message_id",
            "participants",
            "message_count",
            "has_unread",
            "last_message_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class EmailMessageSerializer(serializers.ModelSerializer):
    recipients = EmailRecipientSerializer(many=True, read_only=True)
    attachments = EmailAttachmentSerializer(many=True, read_only=True)
    folder = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()
    is_starred = serializers.SerializerMethodField()

    def _user_state(self, obj):
        states = getattr(obj, "prefetched_user_state", None)
        return states[0] if states else None

    def get_folder(self, obj):
        state = self._user_state(obj)
        return state.folder if state else obj.folder

    def get_is_read(self, obj):
        state = self._user_state(obj)
        return state.is_read if state else obj.is_read

    def get_is_starred(self, obj):
        state = self._user_state(obj)
        return state.is_starred if state else obj.is_starred

    class Meta:
        model = EmailMessage
        fields = [
            "id",
            "mailbox",
            "thread",
            "sender_identity",
            "created_by",
            "direction",
            "status",
            "folder",
            "rfc_message_id",
            "from_address",
            "from_name",
            "envelope_sender",
            "envelope_recipient",
            "to_addresses",
            "cc_addresses",
            "bcc_addresses",
            "reply_to",
            "subject",
            "in_reply_to",
            "references",
            "body_text",
            "body_html",
            "snippet",
            "raw_headers",
            "raw_mime_url",
            "provider",
            "provider_message_id",
            "is_read",
            "is_starred",
            "has_attachments",
            "size_bytes",
            "spam_score",
            "metadata",
            "scheduled_at",
            "sent_at",
            "received_at",
            "created_at",
            "updated_at",
            "recipients",
            "attachments",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "provider_message_id",
            "has_attachments",
            "created_at",
            "updated_at",
            "recipients",
            "attachments",
        ]


class EmailMessageUserStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailMessageUserState
        fields = [
            "id",
            "user",
            "message",
            "folder",
            "is_read",
            "is_starred",
            "archived_at",
            "snoozed_until",
            "deleted_at",
            "last_seen_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        self.fields["message"].queryset = EmailMessage.objects.for_api_user(user)


class OutboundSendAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutboundSendAttempt
        fields = [
            "id",
            "message",
            "provider",
            "attempt_number",
            "status",
            "provider_message_id",
            "idempotency_key",
            "request_payload",
            "response_payload",
            "error_code",
            "error_message",
            "started_at",
            "finished_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class EmailLabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailLabel
        fields = ["id", "mailbox", "name", "color", "created_at"]
        read_only_fields = ["id", "created_at"]


class EmailMessageLabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailMessageLabel
        fields = ["id", "message", "label", "added_at"]
        read_only_fields = ["id", "added_at"]


class MailboxRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MailboxRule
        fields = [
            "id",
            "mailbox",
            "name",
            "priority",
            "conditions",
            "actions",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate_conditions(self, value):
        return self._validate_rule_keys(value, SUPPORTED_CONDITIONS, "conditions")

    def validate_actions(self, value):
        return self._validate_rule_keys(value, SUPPORTED_ACTIONS, "actions")

    def _validate_rule_keys(self, value, supported_keys, label):
        if not isinstance(value, dict):
            raise serializers.ValidationError(f"Rule {label} must be an object.")
        unsupported = sorted(set(value) - supported_keys)
        if unsupported:
            raise serializers.ValidationError(
                f"Unsupported rule {label}: {', '.join(unsupported)}."
            )
        return value


class SuppressedAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = SuppressedAddress
        fields = [
            "id",
            "domain",
            "mailbox",
            "email",
            "reason",
            "source",
            "raw_event",
            "expires_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        mailbox = attrs.get("mailbox", getattr(self.instance, "mailbox", None))
        domain = attrs.get("domain", getattr(self.instance, "domain", None))
        if mailbox and domain and mailbox.domain_id != domain.id:
            raise serializers.ValidationError(
                {"domain": ["Suppression domain must match the mailbox domain."]}
            )
        return attrs


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            "id",
            "mailbox",
            "email",
            "name",
            "is_favorite",
            "times_contacted",
            "last_contacted_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "times_contacted",
            "last_contacted_at",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        self.fields["mailbox"].queryset = Mailbox.objects.writable_for_user(user)

    def validate_email(self, value):
        return value.strip().lower()


class SendEmailSerializer(serializers.Serializer):
    mailbox = serializers.PrimaryKeyRelatedField(queryset=Mailbox.objects.none())
    sender_identity = serializers.PrimaryKeyRelatedField(
        queryset=SenderIdentity.objects.none(),
        required=False,
        allow_null=True,
    )
    to = serializers.ListField(
        child=serializers.JSONField(),
        allow_empty=False,
        required=False,
    )
    to_addresses = serializers.ListField(
        child=serializers.JSONField(),
        allow_empty=False,
        required=False,
        write_only=True,
    )
    cc = serializers.ListField(child=serializers.JSONField(), required=False)
    cc_addresses = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        write_only=True,
    )
    bcc = serializers.ListField(child=serializers.JSONField(), required=False)
    bcc_addresses = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        write_only=True,
    )
    subject = serializers.CharField(max_length=998, allow_blank=True, required=False)
    body_text = serializers.CharField(allow_blank=True, required=False)
    body_html = serializers.CharField(allow_blank=True, required=False)
    reply_to = serializers.EmailField(allow_blank=True, required=False)
    in_reply_to = serializers.CharField(
        max_length=255, allow_blank=True, required=False
    )
    thread = serializers.PrimaryKeyRelatedField(
        queryset=EmailThread.objects.none(),
        required=False,
        allow_null=True,
    )
    reply_to_message = serializers.PrimaryKeyRelatedField(
        queryset=EmailMessage.objects.none(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    metadata = serializers.JSONField(required=False)
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True)
    attachments = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        write_only=True,
    )

    MAX_ATTACHMENTS = 10
    MAX_TOTAL_ATTACHMENT_BYTES = 10 * 1024 * 1024
    DEFAULT_MAX_RECIPIENTS = 50

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        self.fields["mailbox"].queryset = Mailbox.objects.writable_for_user(
            user
        ).send_enabled()
        self.fields["sender_identity"].queryset = SenderIdentity.objects.for_api_user(
            user
        ).active()
        self.fields["thread"].queryset = EmailThread.objects.for_api_user(user)
        self.fields["reply_to_message"].queryset = EmailMessage.objects.for_api_user(
            user
        )

    def validate(self, attrs):
        attrs["to"] = normalize_address_rows(self._recipient_rows(attrs, "to"))
        attrs["cc"] = normalize_address_rows(self._recipient_rows(attrs, "cc"))
        attrs["bcc"] = normalize_address_rows(self._recipient_rows(attrs, "bcc"))

        if not attrs["to"]:
            raise serializers.ValidationError({"to": ["This field is required."]})

        recipient_count = len(attrs["to"]) + len(attrs["cc"]) + len(attrs["bcc"])
        max_recipients = self._max_recipients(attrs["mailbox"])
        if recipient_count > max_recipients:
            raise serializers.ValidationError(
                f"This provider allows at most {max_recipients} recipients."
            )

        if not attrs.get("body_text") and not attrs.get("body_html"):
            raise serializers.ValidationError("Provide body_text or body_html.")

        mailbox = attrs["mailbox"]
        sender_identity = attrs.get("sender_identity")
        if sender_identity and sender_identity.mailbox_id != mailbox.id:
            raise serializers.ValidationError("Sender identity must belong to mailbox.")

        thread = attrs.get("thread")
        if thread is not None and thread.mailbox_id != mailbox.id:
            raise serializers.ValidationError(
                {"thread": ["Thread must belong to mailbox."]}
            )

        reply_to_message = attrs.pop("reply_to_message", None)
        if reply_to_message is not None:
            if reply_to_message.mailbox_id != mailbox.id:
                raise serializers.ValidationError(
                    {"reply_to_message": ["Message must belong to mailbox."]}
                )
            attrs.setdefault("thread", reply_to_message.thread)
            if not attrs.get("in_reply_to") and reply_to_message.rfc_message_id:
                attrs["in_reply_to"] = reply_to_message.rfc_message_id
            attrs["references"] = " ".join(
                filter(
                    None, [reply_to_message.references, reply_to_message.rfc_message_id]
                )
            )
        attrs.setdefault("thread", None)
        attrs.setdefault("in_reply_to", "")
        attrs.setdefault("references", "")

        suppressed = self._suppressed_recipients(
            mailbox, attrs["to"] + attrs["cc"] + attrs["bcc"]
        )
        if suppressed:
            raise serializers.ValidationError(
                {
                    "to": [
                        f"Recipient(s) suppressed and cannot receive mail: {', '.join(suppressed)}"
                    ]
                }
            )

        attrs["attachments"] = self._validate_attachments(
            attrs.get("attachments") or []
        )

        return attrs

    def _recipient_rows(self, attrs, field):
        alias = f"{field}_addresses"
        canonical_rows = attrs.get(field)
        alias_rows = attrs.pop(alias, None)
        if canonical_rows is not None and alias_rows is not None:
            raise serializers.ValidationError(
                {field: [f"Use '{field}' or '{alias}', not both."]}
            )
        return alias_rows if alias_rows is not None else canonical_rows

    def _max_recipients(self, mailbox):
        provider = mailbox.domain.provider
        capabilities = provider.capabilities or {}
        configured = capabilities.get("max_recipients_per_message")
        if configured is None:
            configured = capabilities.get("max_recipients")
        if configured is None:
            configured = self.DEFAULT_MAX_RECIPIENTS
        try:
            return int(configured)
        except (TypeError, ValueError):
            return self.DEFAULT_MAX_RECIPIENTS

    def _suppressed_recipients(self, mailbox, rows):
        emails = {row["email"] for row in rows}
        return sorted(SuppressedAddress.objects.suppressed_emails(mailbox, emails))

    def _validate_attachments(self, attachments):
        if not attachments:
            return []
        if len(attachments) > self.MAX_ATTACHMENTS:
            raise serializers.ValidationError(
                {
                    "attachments": [
                        f"At most {self.MAX_ATTACHMENTS} attachments are allowed."
                    ]
                }
            )
        normalized = []
        total_size = 0
        for item in attachments:
            if not isinstance(item, dict):
                raise serializers.ValidationError(
                    {"attachments": ["Each attachment must be an object."]}
                )
            filename = (item.get("filename") or "").strip()
            content = item.get("content") or ""
            if not filename:
                raise serializers.ValidationError(
                    {"attachments": ["Each attachment requires a filename."]}
                )
            if not content:
                raise serializers.ValidationError(
                    {
                        "attachments": [
                            "Each attachment requires base64-encoded content."
                        ]
                    }
                )
            try:
                size = len(base64.b64decode(content, validate=True))
            except (binascii.Error, ValueError):
                raise serializers.ValidationError(
                    {
                        "attachments": [
                            f"Attachment '{filename}' has invalid base64 content."
                        ]
                    }
                )
            total_size += size
            normalized.append(
                {
                    "filename": filename,
                    "content_type": item.get("content_type")
                    or "application/octet-stream",
                    "content": content,
                    "content_id": item.get("content_id") or "",
                }
            )
        if total_size > self.MAX_TOTAL_ATTACHMENT_BYTES:
            raise serializers.ValidationError(
                {"attachments": ["Total attachment size exceeds the 10MB limit."]}
            )
        return normalized

    def create(self, validated_data):
        message, attempt = EmailMessage.objects.create_outbound_message(
            mailbox=validated_data["mailbox"],
            created_by=self.context["request"].user,
            sender_identity=validated_data.get("sender_identity"),
            to_addresses=validated_data["to"],
            cc_addresses=validated_data.get("cc", []),
            bcc_addresses=validated_data.get("bcc", []),
            subject=validated_data.get("subject", ""),
            body_text=validated_data.get("body_text", ""),
            body_html=validated_data.get("body_html", ""),
            reply_to=validated_data.get("reply_to", ""),
            metadata=validated_data.get("metadata", {}),
            scheduled_at=validated_data.get("scheduled_at"),
            attachments=validated_data.get("attachments", []),
            thread=validated_data.get("thread"),
            in_reply_to=validated_data.get("in_reply_to", ""),
            references=validated_data.get("references", ""),
        )
        message._send_attempt = attempt
        return message


class MessageStatePatchSerializer(serializers.Serializer):
    is_read = serializers.BooleanField(required=False)
    is_starred = serializers.BooleanField(required=False)
    folder = serializers.ChoiceField(
        choices=EmailMessage._meta.get_field("folder").choices,
        required=False,
    )
