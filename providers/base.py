"""Provider-agnostic interface and normalized payload shapes.

Every concrete provider (Postmark, SES, Mailgun, ...) implements
``BaseEmailProvider`` and is looked up via ``providers.registry.get_provider``.
Webhook payloads are normalized to the dataclasses below so the generic
ingestion logic in ``providers.ingest`` never has to know which provider a
message came from.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NormalizedAddress:
    email: str
    name: str = ""


@dataclass
class NormalizedAttachment:
    filename: str
    content_type: str = "application/octet-stream"
    content_b64: str = ""
    content_id: str = ""
    is_inline: bool = False
    declared_size: int = 0


@dataclass
class NormalizedInboundMessage:
    """Provider-agnostic shape of an inbound email, ready for EmailMessage.objects.create()."""

    from_address: str
    from_name: str = ""
    to: list[NormalizedAddress] = field(default_factory=list)
    cc: list[NormalizedAddress] = field(default_factory=list)
    bcc: list[NormalizedAddress] = field(default_factory=list)
    envelope_sender: str = ""
    envelope_recipient: str = ""
    reply_to: str = ""
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    rfc_message_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    raw_headers: dict = field(default_factory=dict)
    attachments: list[NormalizedAttachment] = field(default_factory=list)
    provider_message_id: str = ""
    received_at: Optional[datetime] = None
    size_bytes: int = 0
    spam_score: Optional[float] = None
    auth_results: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class NormalizedDeliveryEvent:
    """Provider-agnostic shape of a delivery/bounce/open/click/... event."""

    event_type: str
    provider_message_id: str
    provider_event_id: str = ""
    recipient: str = ""
    reason: str = ""
    link_url: str = ""
    occurred_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedWebhookEvent:
    """Result of normalizing one webhook payload."""

    kind: str  # "inbound" | "delivery_event" | "unknown"
    event_type: str
    inbound: Optional[NormalizedInboundMessage] = None
    delivery_event: Optional[NormalizedDeliveryEvent] = None


class BaseEmailProvider(ABC):
    """Interface every email provider integration must implement."""

    provider_type: str = ""

    def __init__(self, provider):
        self.provider = provider

    @property
    def capabilities(self) -> dict:
        return self.provider.capabilities or {}

    def supports(self, capability: str) -> bool:
        return bool(self.capabilities.get(capability))

    @classmethod
    @abstractmethod
    def resolve_provider_for_webhook(cls, request, payload):
        """Resolve the ``EmailProvider`` row a webhook request belongs to."""
        raise NotImplementedError

    @abstractmethod
    def resolve_domain(self, payload: dict):
        """Resolve the ``Domain`` a webhook payload belongs to, or None."""
        raise NotImplementedError

    @abstractmethod
    def verify_webhook(self, request, domain) -> Optional[bool]:
        """Validate webhook authenticity.

        Returns True/False if a secret is configured, or None if no secret
        is configured (caller decides the policy for that case).
        """
        raise NotImplementedError

    @abstractmethod
    def classify_webhook(self, payload: dict) -> tuple[str, str, str]:
        """Classify a raw payload without fully parsing it.

        Returns ``(kind, event_type, provider_event_id)`` where ``kind`` is
        "inbound", "delivery_event", or "unknown", and ``provider_event_id``
        is a stable id used for idempotent storage (or "").
        """
        raise NotImplementedError

    @abstractmethod
    def parse_webhook(self, raw_webhook) -> ParsedWebhookEvent:
        """Normalize a stored ``ProviderWebhookLog`` payload."""
        raise NotImplementedError

    @abstractmethod
    def send(self, message, attempt):
        """Send an outbound EmailMessage, updating message/attempt status in place."""
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> tuple[bool, str]:
        """Perform a lightweight provider API call to verify credentials/connectivity.

        Returns ``(True, "")`` on success or ``(False, error_message)`` on failure.
        """
        raise NotImplementedError
