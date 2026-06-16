"""Request/task correlation IDs and JSON log formatting.

``request_id`` is stored in a contextvar so any log record emitted while
handling a request or running a Celery task can be tagged with the same id,
without threading it through every function signature.
"""

import contextvars
import json
import logging
from datetime import datetime, timezone

_request_id_var = contextvars.ContextVar("request_id", default="-")


def get_request_id():
    return _request_id_var.get()


def set_request_id(value):
    return _request_id_var.set(value or "-")


def reset_request_id(token):
    _request_id_var.reset(token)


def _request_id_from_record(record):
    request = getattr(record, "request", None)
    return getattr(request, "request_id", None) or "-"


class RequestIDFilter(logging.Filter):
    """Attach the current ``request_id`` to every log record."""

    def filter(self, record):
        request_id = get_request_id()
        if request_id == "-":
            request_id = _request_id_from_record(record)
        record.request_id = request_id
        return True


class JSONFormatter(logging.Formatter):
    """Render log records as single-line JSON for log-aggregator friendly output."""

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str)
