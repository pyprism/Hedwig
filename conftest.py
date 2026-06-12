"""
Root pytest conftest.

- Forces Celery to run tasks synchronously (CELERY_TASK_ALWAYS_EAGER) so tests
  never need a live RabbitMQ broker.
"""

import json

import pytest

# Celery eager mode for all tests


@pytest.fixture(autouse=True)
def celery_eager_mode(settings):
    """Make every Celery task execute synchronously & ignore failures."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = False
