"""Short-lived WS ownership shared by the consumer and REST workers."""

import logging
from uuid import uuid4

from django.core.cache import cache


logger = logging.getLogger(__name__)
HEALTH_TTL_SECONDS = 30


class LiveStreamHealth:
    def __init__(self):
        self.session_id = uuid4().hex

    def mark_alive(self):
        # Called only after a validated snapshot or a confirmed protocol pong.
        cache.set(f"live-ws:health:{self.session_id}", True, timeout=HEALTH_TTL_SECONDS)

    def clear(self):
        try:
            cache.delete(f"live-ws:health:{self.session_id}")
        except Exception as exc:
            # A dead process/cache cannot retain priority beyond the TTL.
            logger.warning("Cannot clear WS health (%s)", type(exc).__name__)


def is_ws_session_active(session_id):
    if not isinstance(session_id, str) or not session_id or len(session_id) > 64:
        return False
    try:
        return cache.get(f"live-ws:health:{session_id}") is True
    except Exception as exc:
        logger.warning("Cannot read WS health; using REST fallback (%s)", type(exc).__name__)
        return False


def has_ws_priority(match):
    if match.live_state_needs_refresh:
        return False  # Explicit absence/removal permits targeted reconciliation.
    raw = match.raw_data if isinstance(match.raw_data, dict) else {}
    stream = raw.get("live_stream")
    return isinstance(stream, dict) and is_ws_session_active(stream.get("session_id"))
