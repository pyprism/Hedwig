from rest_framework.routers import DefaultRouter

from hedwig.views import (
    ContactViewSet,
    EmailAttachmentViewSet,
    EmailLabelViewSet,
    EmailMessageLabelViewSet,
    EmailMessageUserStateViewSet,
    EmailMessageViewSet,
    EmailRecipientViewSet,
    EmailThreadViewSet,
    MailboxAliasViewSet,
    MailboxRuleViewSet,
    MailboxViewSet,
    OutboundSendAttemptViewSet,
    SenderIdentityViewSet,
    SuppressedAddressViewSet,
    UserMailboxAccessViewSet,
)


router = DefaultRouter()
router.register("mailboxes", MailboxViewSet, basename="mailbox")
router.register("mailbox-aliases", MailboxAliasViewSet, basename="mailbox-alias")
router.register("sender-identities", SenderIdentityViewSet, basename="sender-identity")
router.register("mailbox-accesses", UserMailboxAccessViewSet, basename="mailbox-access")
router.register("threads", EmailThreadViewSet, basename="thread")
router.register("messages", EmailMessageViewSet, basename="message")
router.register("recipients", EmailRecipientViewSet, basename="recipient")
router.register(
    "message-states", EmailMessageUserStateViewSet, basename="message-state"
)
router.register("send-attempts", OutboundSendAttemptViewSet, basename="send-attempt")
router.register("attachments", EmailAttachmentViewSet, basename="attachment")
router.register("labels", EmailLabelViewSet, basename="label")
router.register("message-labels", EmailMessageLabelViewSet, basename="message-label")
router.register("mailbox-rules", MailboxRuleViewSet, basename="mailbox-rule")
router.register(
    "suppressed-addresses", SuppressedAddressViewSet, basename="suppressed-address"
)
router.register("contacts", ContactViewSet, basename="contact")

urlpatterns = router.urls
