import os

from django.core.exceptions import ImproperlyConfigured


def require_env(name):
    """Read a required environment variable, raising in prod if it's missing."""
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(
            f"The '{name}' environment variable must be set when debug=False."
        )
    return value
