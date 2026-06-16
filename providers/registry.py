"""Provider implementation lookup.

Keeps ``providers.base`` free of imports for concrete providers (avoiding
circular imports) while giving the rest of the codebase a single place to
turn an ``EmailProvider`` row into a ``BaseEmailProvider`` instance.
"""

from utils.enums import ProviderType


REGISTERED_PROVIDER_TYPES = (ProviderType.POSTMARK,)


def get_registered_provider_types():
    return REGISTERED_PROVIDER_TYPES


def is_registered_provider_type(provider_type):
    return provider_type in REGISTERED_PROVIDER_TYPES


def get_provider_class(provider_type):
    if provider_type == ProviderType.POSTMARK:
        from providers.postmark import PostmarkProvider

        return PostmarkProvider
    raise ValueError(f"No provider implementation registered for '{provider_type}'.")


def get_provider(email_provider):
    """Return a ``BaseEmailProvider`` instance for the given ``EmailProvider`` row."""
    return get_provider_class(email_provider.provider_type)(email_provider)
