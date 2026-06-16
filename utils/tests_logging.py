import logging
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from utils.logging import (
    RequestIDFilter,
    get_request_id,
    reset_request_id,
    set_request_id,
)
from utils.middleware import RequestIDMiddleware


class DummyResponse(dict):
    def __init__(self):
        super().__init__()
        self.close_count = 0

    def close(self):
        self.close_count += 1


@pytest.fixture(autouse=True)
def clear_request_id():
    token = set_request_id("-")
    yield
    reset_request_id(token)


def _log_record(**extra):
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="message",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_request_id_remains_available_until_response_close():
    request = RequestFactory().get("/", HTTP_X_REQUEST_ID="req-123")
    middleware = RequestIDMiddleware(lambda request: DummyResponse())

    response = middleware(request)

    record = _log_record()
    RequestIDFilter().filter(record)
    assert record.request_id == "req-123"

    response.close()
    response.close()

    assert response.close_count == 2
    assert get_request_id() == "-"


def test_request_id_filter_falls_back_to_log_record_request():
    record = _log_record(request=SimpleNamespace(request_id="req-from-record"))

    RequestIDFilter().filter(record)

    assert record.request_id == "req-from-record"
