import uuid
from collections import OrderedDict

from django.contrib.auth import get_user_model
from django.utils import timezone

from utils.logging import reset_request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware:
    """Tag each request with a correlation id, propagated to logs and the response."""

    LAST_SEEN_INTERVAL_SECONDS = 300
    LAST_SEEN_CACHE_MAX_SIZE = 4096
    _last_seen_cache = OrderedDict()

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.request_id = request_id
        token = set_request_id(request_id)
        try:
            response = self.get_response(request)
        except Exception:
            reset_request_id(token)
            raise

        self._touch_last_seen(request)

        original_close = response.close
        request_id_reset = False

        def close_with_request_id_reset(*args, **kwargs):
            nonlocal request_id_reset
            try:
                return original_close(*args, **kwargs)
            finally:
                if not request_id_reset:
                    reset_request_id(token)
                    request_id_reset = True

        response.close = close_with_request_id_reset
        response[REQUEST_ID_HEADER] = request_id
        return response

    def _touch_last_seen(self, request):
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return

        now = timezone.now()
        last_seen_at = self._last_seen_cache.get(user.pk)
        if (
            last_seen_at is not None
            and (now - last_seen_at).total_seconds() < self.LAST_SEEN_INTERVAL_SECONDS
        ):
            self._last_seen_cache.move_to_end(user.pk)
            return

        get_user_model().objects.filter(pk=user.pk).update(last_seen_at=now)
        self._last_seen_cache[user.pk] = now
        self._last_seen_cache.move_to_end(user.pk)
        while len(self._last_seen_cache) > self.LAST_SEEN_CACHE_MAX_SIZE:
            self._last_seen_cache.popitem(last=False)
