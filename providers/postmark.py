import base64
import hmac
import re
from datetime import timezone as datetime_timezone
from email.utils import getaddresses, parsedate_to_datetime

import requests
from django.core.exceptions import ValidationError
from django.utils import timezone

from providers.base import (
    BaseEmailProvider,
    NormalizedAddress,
    NormalizedAttachment,
    NormalizedDeliveryEvent,
    NormalizedInboundMessage,
    ParsedWebhookEvent,
)
from providers.models import Domain, EmailProvider
from utils.enums import EmailStatus, EventType, ProviderType, SendAttemptStatus
from utils.s3 import get_s3_uploader


POSTMARK_BASE_URL = "https://api.postmarkapp.com"
POSTMARK_METADATA_KEY_LIMIT = 20
POSTMARK_METADATA_VALUE_LIMIT = 80


def format_address(email, name=""):
    if name:
        return f"{name} <{email}>"
    return email


def join_addresses(addresses):
    return ", ".join(
        format_address(row["email"], row.get("name", "")) for row in addresses
    )


def normalize_postmark_metadata(metadata):
    normalized = {}
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        normalized[str(key)[:POSTMARK_METADATA_KEY_LIMIT]] = str(value)[
            :POSTMARK_METADATA_VALUE_LIMIT
        ]
    return normalized


def normalize_email(value):
    return (value or "").strip().lower()


def postmark_full_to_rows(value):
    rows = []
    for item in value or []:
        email = normalize_email(item.get("Email"))
        if email:
            rows.append(
                {
                    "email": email,
                    "name": item.get("Name") or "",
                    "mailbox_hash": item.get("MailboxHash") or "",
                }
            )
    return rows


def address_string_to_rows(value):
    rows = []
    for name, email in getaddresses([value or ""]):
        email = normalize_email(email)
        if email:
            rows.append({"email": email, "name": name or ""})
    return rows


def payload_recipients(payload, full_key, text_key):
    rows = postmark_full_to_rows(payload.get(full_key))
    if rows:
        return rows
    return address_string_to_rows(payload.get(text_key))


def payload_headers_to_dict(payload):
    headers = {}
    for item in payload.get("Headers") or []:
        name = item.get("Name")
        if name:
            headers[name] = item.get("Value", "")
    return headers


def parse_postmark_date(value):
    if not value:
        return timezone.now()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return timezone.now()
    if parsed is None:
        return timezone.now()
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=datetime_timezone.utc)
    return parsed


AUTH_RESULT_PATTERN = re.compile(r"(spf|dkim|dmarc)=(\w+)", re.IGNORECASE)


def parse_auth_results(headers):
    """Extract spf/dkim/dmarc verdicts from an Authentication-Results header."""
    raw = headers.get("Authentication-Results") or ""
    results = {}
    for key, value in AUTH_RESULT_PATTERN.findall(raw):
        results[key.lower()] = value.lower()
    return results


def event_type_from_payload(payload):
    record_type = (payload.get("RecordType") or "").lower()
    message_stream = (payload.get("MessageStream") or "").lower()
    if (
        message_stream == "inbound"
        or payload.get("FromFull")
        or payload.get("TextBody")
    ):
        return "inbound"
    if record_type in {"delivery", "delivered"}:
        return EventType.DELIVERED
    if record_type in {"bounce", "hardbounce", "softbounce"}:
        return EventType.BOUNCED
    if record_type == "open":
        return EventType.OPENED
    if record_type == "click":
        return EventType.CLICKED
    if record_type in {"spamcomplaint", "spam complaint"}:
        return EventType.COMPLAINED
    if record_type in {"subscriptionchange", "unsubscribe", "unsubscribed"}:
        return EventType.UNSUBSCRIBED
    return record_type or "unknown"


def provider_event_id_for(payload, event_type):
    raw_id = (
        payload.get("ID") or payload.get("MessageID") or payload.get("MessageId") or ""
    )
    return f"{event_type}:{raw_id}" if raw_id else ""


def recipient_domain_names(payload):
    emails = []
    for key in ("ToFull", "CcFull", "BccFull"):
        emails.extend(row["email"] for row in postmark_full_to_rows(payload.get(key)))
    for key in ("To", "Cc", "Bcc", "OriginalRecipient", "DeliveredTo"):
        emails.extend(row["email"] for row in address_string_to_rows(payload.get(key)))
    return [email.rsplit("@", 1)[1] for email in emails if "@" in email]


def first_payload_recipient(payload, *keys):
    for key in keys:
        rows = address_string_to_rows(payload.get(key))
        if rows:
            return rows[0]["email"]
    return ""


def extract_envelope_sender(headers):
    value = headers.get("Return-Path") or headers.get("Return-path") or ""
    return normalize_email(value.strip("<>"))


def _address_rows_to_normalized(rows):
    return [
        NormalizedAddress(email=row["email"], name=row.get("name", "")) for row in rows
    ]


class PostmarkProvider(BaseEmailProvider):
    provider_type = ProviderType.POSTMARK

    @classmethod
    def resolve_provider_for_webhook(cls, request, payload):
        provider_id = request.query_params.get("provider") or payload.get(
            "HedwigProviderID"
        )
        queryset = EmailProvider.objects.filter(
            provider_type=ProviderType.POSTMARK, is_active=True
        )
        if provider_id:
            return queryset.get(pk=provider_id)

        providers = list(queryset[:2])
        if len(providers) == 1:
            return providers[0]
        raise ValidationError(
            "Postmark provider is ambiguous. Pass ?provider=<provider_id>."
        )

    def resolve_domain(self, payload):
        domain_names = recipient_domain_names(payload)
        if domain_names:
            domain = (
                Domain.objects.inbound_enabled()
                .filter(provider=self.provider, name__in=domain_names)
                .first()
            )
            if domain:
                return domain

        domains = list(
            Domain.objects.inbound_enabled().filter(provider=self.provider)[:2]
        )
        if len(domains) == 1:
            return domains[0]
        return None

    def verify_webhook(self, request, domain):
        expected = domain.webhook_secret if domain and domain.webhook_secret else ""
        expected = expected or self.provider.webhook_signing_secret
        if not expected:
            return None

        supplied = (
            request.headers.get("X-Hedwig-Webhook-Secret")
            or request.headers.get("X-Hookdeck-Webhook-Secret")
            or request.query_params.get("secret")
            or ""
        )
        return hmac.compare_digest(supplied, expected)

    def classify_webhook(self, payload):
        event_type = event_type_from_payload(payload)
        if event_type == "inbound":
            kind = "inbound"
        elif event_type in EventType.values:
            kind = "delivery_event"
        else:
            kind = "unknown"
        return kind, event_type, provider_event_id_for(payload, event_type)

    def parse_webhook(self, raw_webhook):
        payload = raw_webhook.payload or {}
        kind, event_type, _ = self.classify_webhook(payload)
        if kind == "inbound":
            return ParsedWebhookEvent(
                kind=kind, event_type=event_type, inbound=self._parse_inbound(payload)
            )
        if kind == "delivery_event":
            return ParsedWebhookEvent(
                kind=kind,
                event_type=event_type,
                delivery_event=self._parse_delivery_event(payload, event_type),
            )
        return ParsedWebhookEvent(kind="unknown", event_type=event_type)

    def _parse_inbound(self, payload):
        to_rows = payload_recipients(payload, "ToFull", "To")
        cc_rows = payload_recipients(payload, "CcFull", "Cc")
        bcc_rows = payload_recipients(payload, "BccFull", "Bcc")
        headers = payload_headers_to_dict(payload)
        from_full = payload.get("FromFull") or {}
        from_address = normalize_email(from_full.get("Email") or payload.get("From"))
        envelope_recipient = first_payload_recipient(
            payload,
            "OriginalRecipient",
            "DeliveredTo",
            "Recipient",
        )

        spam_score = None
        try:
            spam_score = float(headers.get("X-Spam-Score", ""))
        except ValueError:
            spam_score = None

        return NormalizedInboundMessage(
            from_address=from_address,
            from_name=from_full.get("Name") or payload.get("FromName") or "",
            to=_address_rows_to_normalized(to_rows),
            cc=_address_rows_to_normalized(cc_rows),
            bcc=_address_rows_to_normalized(bcc_rows),
            envelope_sender=extract_envelope_sender(headers) or from_address,
            envelope_recipient=envelope_recipient,
            reply_to=payload.get("ReplyTo") or "",
            subject=payload.get("Subject") or "",
            body_text=payload.get("TextBody") or "",
            body_html=payload.get("HtmlBody") or "",
            rfc_message_id=headers.get("Message-ID") or None,
            in_reply_to=headers.get("In-Reply-To") or None,
            references=headers.get("References") or None,
            raw_headers=headers,
            attachments=[
                NormalizedAttachment(
                    filename=attachment.get("Name") or "attachment",
                    content_type=attachment.get("ContentType")
                    or "application/octet-stream",
                    content_b64=attachment.get("Content") or "",
                    content_id=attachment.get("ContentID") or "",
                    is_inline=bool(attachment.get("ContentID")),
                    declared_size=int(attachment.get("ContentLength") or 0),
                )
                for attachment in payload.get("Attachments") or []
            ],
            provider_message_id=payload.get("MessageID") or "",
            received_at=parse_postmark_date(payload.get("Date")),
            size_bytes=int(payload.get("MessageSize") or 0),
            spam_score=spam_score,
            auth_results=parse_auth_results(headers),
            metadata={
                "postmark": {
                    "mailbox_hash": payload.get("MailboxHash") or "",
                    "stripped_text_reply": payload.get("StrippedTextReply") or "",
                    "tag": payload.get("Tag") or "",
                },
            },
        )

    def _parse_delivery_event(self, payload, event_type):
        provider_message_id = payload.get("MessageID") or payload.get("MessageId") or ""
        occurred_at = parse_postmark_date(
            payload.get("DeliveredAt")
            or payload.get("BouncedAt")
            or payload.get("ReceivedAt")
            or payload.get("ChangedAt")
            or payload.get("Received")
        )
        return NormalizedDeliveryEvent(
            event_type=event_type,
            provider_message_id=provider_message_id,
            provider_event_id=provider_event_id_for(payload, event_type),
            recipient=normalize_email(payload.get("Email") or payload.get("Recipient")),
            reason=payload.get("Description")
            or payload.get("Details")
            or payload.get("Type")
            or "",
            link_url=payload.get("OriginalLink") or payload.get("Url") or "",
            occurred_at=occurred_at,
            metadata={"postmark": payload},
        )

    def send(self, message, attempt):
        return PostmarkClient(self.provider).send_message(message, attempt)

    def health_check(self):
        try:
            client = PostmarkClient(self.provider)
        except ValidationError as exc:
            return False, "; ".join(exc.messages)
        return client.check_health()


class PostmarkClient:
    def __init__(self, provider):
        self.provider = provider
        self.base_url = (provider.api_base_url or POSTMARK_BASE_URL).rstrip("/")
        self.server_token = (
            provider.credentials.get("server_token")
            or provider.credentials.get("api_token")
            or provider.credential_reference
        )
        if not self.server_token:
            raise ValidationError("Postmark provider is missing a server token.")

    def send_message(self, message, attempt):
        metadata = normalize_postmark_metadata(
            message.metadata.get("postmark_metadata", {})
        )
        metadata.update(
            normalize_postmark_metadata(
                {
                    "hedwig_msg_id": str(message.id),
                    "hedwig_idem": (
                        attempt.idempotency_key[:16] if attempt.idempotency_key else ""
                    ),
                }
            )
        )
        payload = {
            "From": format_address(message.from_address, message.from_name or ""),
            "To": join_addresses(message.to_addresses),
            "Subject": message.subject,
            "TextBody": message.body_text,
            "HtmlBody": message.body_html,
            "MessageStream": message.metadata.get("message_stream", "outbound"),
            "Metadata": metadata,
        }
        if message.cc_addresses:
            payload["Cc"] = join_addresses(message.cc_addresses)
        if message.bcc_addresses:
            payload["Bcc"] = join_addresses(message.bcc_addresses)
        if message.reply_to:
            payload["ReplyTo"] = message.reply_to
        if message.metadata.get("tag"):
            payload["Tag"] = message.metadata["tag"]
        if "track_opens" in message.metadata:
            payload["TrackOpens"] = message.metadata["track_opens"]
        if "track_links" in message.metadata:
            payload["TrackLinks"] = message.metadata["track_links"]
        headers = dict(message.raw_headers or {})
        if message.in_reply_to:
            headers["In-Reply-To"] = message.in_reply_to
        if message.references:
            headers["References"] = message.references
        if message.rfc_message_id:
            headers["Message-ID"] = message.rfc_message_id
        if headers:
            payload["Headers"] = [
                {"Name": key, "Value": value} for key, value in headers.items()
            ]
        attachments_payload = self._build_attachments_payload(message)
        if attachments_payload:
            payload["Attachments"] = attachments_payload

        attempt.status = SendAttemptStatus.SENDING
        attempt.started_at = timezone.now()
        attempt.request_payload = payload
        attempt.save(update_fields=["status", "started_at", "request_payload"])

        try:
            response = requests.post(
                f"{self.base_url}/email",
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Postmark-Server-Token": self.server_token,
                },
                timeout=20,
            )
            data = response.json()
        except requests.RequestException as exc:
            mark_send_failed(message, attempt, "request_error", str(exc))
            raise TransientSendError(str(exc)) from exc
        except ValueError as exc:
            mark_send_failed(message, attempt, "invalid_response", response.text)
            raise TransientSendError("Postmark returned a non-JSON response.") from exc

        attempt.response_payload = data
        attempt.finished_at = timezone.now()

        if response.status_code >= 400 or data.get("ErrorCode"):
            transient = response.status_code >= 500
            attempt.status = SendAttemptStatus.FAILED
            attempt.error_code = str(data.get("ErrorCode") or response.status_code)
            attempt.error_message = data.get("Message", "Postmark send failed.")
            message.status = EmailStatus.FAILED
            message.save(update_fields=["status", "updated_at"])
            attempt.save(
                update_fields=[
                    "status",
                    "response_payload",
                    "error_code",
                    "error_message",
                    "finished_at",
                ]
            )
            if transient:
                raise TransientSendError(attempt.error_message)
            raise PermanentSendError(attempt.error_message)

        provider_message_id = data.get("MessageID", "")
        attempt.status = SendAttemptStatus.SENT
        attempt.provider_message_id = provider_message_id
        message.status = EmailStatus.SENT
        message.provider_message_id = provider_message_id
        message.sent_at = timezone.now()
        message.save(
            update_fields=[
                "status",
                "provider_message_id",
                "sent_at",
                "updated_at",
            ]
        )
        attempt.save(
            update_fields=[
                "status",
                "provider_message_id",
                "response_payload",
                "error_code",
                "error_message",
                "finished_at",
            ]
        )
        return data

    def check_health(self):
        """Verify the server token/connectivity via Postmark's GET /server endpoint."""
        try:
            response = requests.get(
                f"{self.base_url}/server",
                headers={
                    "Accept": "application/json",
                    "X-Postmark-Server-Token": self.server_token,
                },
                timeout=10,
            )
        except requests.RequestException as exc:
            return False, str(exc)

        if response.status_code >= 400:
            try:
                message = response.json().get("Message", response.text)
            except ValueError:
                message = response.text
            return False, message[:500]

        return True, ""

    def _build_attachments_payload(self, message):
        attachments_payload = []
        uploader = None
        for attachment in message.attachments.all():
            if not attachment.file:
                continue
            uploader = uploader or get_s3_uploader()
            content_bytes = uploader.download_file(attachment.file)
            if content_bytes is None:
                continue
            entry = {
                "Name": attachment.filename,
                "Content": base64.b64encode(content_bytes).decode("ascii"),
                "ContentType": attachment.content_type or "application/octet-stream",
            }
            if attachment.content_id:
                entry["ContentID"] = attachment.content_id
            attachments_payload.append(entry)
        return attachments_payload


class TransientSendError(ValidationError):
    """Raised for retryable provider/network errors (timeouts, 5xx)."""


class PermanentSendError(ValidationError):
    """Raised for non-retryable provider errors (4xx, validation)."""


def mark_send_failed(message, attempt, code, error):
    attempt.status = SendAttemptStatus.FAILED
    attempt.error_code = code
    attempt.error_message = error
    attempt.finished_at = timezone.now()
    attempt.save(update_fields=["status", "error_code", "error_message", "finished_at"])
    message.status = EmailStatus.FAILED
    message.save(update_fields=["status", "updated_at"])
