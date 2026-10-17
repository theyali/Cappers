"""Prematch odds notifications enqueue REST work, never apply WS prices."""

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime


class OddsMessageError(ValueError):
    pass


ODDS_MESSAGE_TYPES = {"prematch.odds.available", "prematch.odds.updated"}


def odds_sport_ids():
    project_ids = {int(sport["id"]) for sport in settings.NEUROKEFF_SPORTS}
    configured = settings.NEUROKEFF_ODDS_WS_SPORTS or project_ids
    try:
        selected = {int(value) for value in configured}
    except (ValueError, TypeError):
        raise OddsMessageError("Odds WebSocket sport PKs must be positive integers") from None
    if not selected or min(selected) < 1 or not selected <= project_ids:
        raise OddsMessageError("Odds WebSocket sports must be configured in NEUROKEFF_SPORTS")
    return selected


def validate_odds_message(message):
    if (not isinstance(message, dict) or not isinstance(message.get("type"), str)
            or message["type"] not in ODDS_MESSAGE_TYPES):
        raise OddsMessageError("Unsupported odds message type")
    if message.get("phase") != "prematch" or any(
        type(message.get(key)) is not int or message[key] < 1
        for key in ("game_pk", "sport_pk")
    ):
        raise OddsMessageError("Invalid prematch odds identity/phase")
    bookmaker = message.get("bookmaker_pk")
    # An updated line may no longer contain any bookmaker. This is a hint,
    # never a selector for which bookmakers/prices to persist from REST.
    if not (bookmaker is None and message["type"] == "prematch.odds.updated") and (
        type(bookmaker) is not int or bookmaker < 1
    ):
        raise OddsMessageError("Invalid odds bookmaker identity")
    if "changed" in message and (
        not isinstance(message["changed"], list)
        or any(not isinstance(field, str) or not field for field in message["changed"])
    ):
        raise OddsMessageError("Invalid odds changed fields")
    try:
        event_id = str(UUID(message["event_id"]))
        stamp = parse_datetime(message["occurred_at"])
    except (KeyError, ValueError, TypeError, AttributeError):
        raise OddsMessageError("Invalid odds event ID/timestamp") from None
    if stamp is None or timezone.is_naive(stamp) or stamp > timezone.now() + timedelta(seconds=60):
        raise OddsMessageError("Invalid odds timestamp")
    return event_id


def queue_odds_message(message, sport_ids):
    from game.tasks import refresh_prematch_match_odds

    event_id = validate_odds_message(message)
    if message["sport_pk"] not in sport_ids:
        return False
    event_key = f"odds-ws:event:{event_id}"
    if cache.get(event_key):
        return False
    # Never throttle distinct events by game: an update can arrive immediately
    # after an earlier REST response, including while its worker is still busy.
    # The task's shared lock serializes HTTP, without dropping the later signal.
    refresh_prematch_match_odds.apply_async(
        args=[message["game_pk"], message["sport_pk"], message["type"]], retry=False,
    )
    # Mark only after successful publication; event_id isn't a version or order.
    cache.set(event_key, True, timeout=86400)
    return True


def queue_prematch_reconciliation(sport_ids):
    from game.tasks import reconcile_prematch_odds

    queued = 0
    for sport_id in sorted(sport_ids):
        key = f"odds-ws:reconcile:{sport_id}"
        if not cache.add(key, 1, timeout=60):
            continue
        try:
            reconcile_prematch_odds.apply_async(args=[sport_id], retry=False)
        except Exception:
            cache.delete(key)
            raise
        queued += 1
    return queued
