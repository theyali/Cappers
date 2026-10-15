"""Neurokeff live-state messages only. Never sync odds, statistics or events here."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from game.models import Match, Provider
from game.services.match_sync import MatchSyncService
from game.services.live_stream_health import is_ws_session_active


class LiveMessageError(ValueError):
    pass


def live_sport_ids():
    configured = settings.NEUROKEFF_LIVE_WS_SPORTS or [item["id"] for item in settings.NEUROKEFF_SPORTS]
    try:
        values = {int(value) for value in configured}
    except (ValueError, TypeError):
        raise LiveMessageError("WebSocket sport PKs must be positive integers") from None
    if not values or min(values) < 1:
        raise LiveMessageError("Configure at least one WebSocket sport PK")
    return values


def _positive_id(value):
    return type(value) is int and value > 0


def _timestamp(value):
    try:
        stamp = parse_datetime(value) if isinstance(value, str) else None
    except ValueError:
        stamp = None
    if stamp is None or timezone.is_naive(stamp) or stamp > timezone.now() + timedelta(seconds=60):
        raise LiveMessageError("Missing or invalid live message timestamp")
    return stamp


def validate_match(state):
    if not isinstance(state, dict) or any(not _positive_id(state.get(key)) for key in (
        "game_pk", "sport_pk", "home_team_pk", "away_team_pk",
    )):
        raise LiveMessageError("Invalid match identity")
    if state.get("status") not in {str(code) for code in range(9)}:
        raise LiveMessageError("Unknown match status")
    score = state.get("score")
    if not isinstance(score, dict) or any(key not in score or (
        score[key] is not None and (type(score[key]) is not int or score[key] < 0)
    ) for key in ("home", "away")):
        raise LiveMessageError("Invalid match score")
    clock = state.get("clock")
    if clock is not None:
        if not isinstance(clock, dict):
            raise LiveMessageError("Invalid match clock")
        for key in ("minute", "second"):
            number = clock.get(key)
            if number is not None and (type(number) is not int or number < 0):
                raise LiveMessageError("Invalid clock number")
        if clock.get("second") is not None and clock["second"] > 59:
            raise LiveMessageError("Invalid clock second")
        if not isinstance(clock.get("display", ""), str) or len(clock.get("display", "")) > 32:
            raise LiveMessageError("Invalid clock display")
    if state.get("period") is not None and not isinstance(state["period"], dict):
        raise LiveMessageError("Invalid match period")
    if not isinstance(state.get("periods"), dict):
        raise LiveMessageError("Invalid match periods")
    if state.get("point") is not None and not isinstance(state["point"], str):
        raise LiveMessageError("Invalid tennis point")
    if state.get("serving_team_pk") is not None and not _positive_id(state["serving_team_pk"]):
        raise LiveMessageError("Invalid serving team")
    return state


def validate_snapshot(message):
    observed_at = _timestamp(message.get("generated_at"))
    states = message.get("matches")
    if not isinstance(states, list):
        raise LiveMessageError("Snapshot matches must be an array")
    states = [validate_match(state) for state in states]
    if any(state["status"] != "1" for state in states):
        raise LiveMessageError("Snapshot contains non-live matches")
    ids = [state["game_pk"] for state in states]
    if len(ids) != len(set(ids)):
        raise LiveMessageError("Snapshot contains duplicate matches")
    return observed_at, states


class LiveStateStream:
    def __init__(self, sport_ids=None, session_id=None):
        self.sport_ids = set(sport_ids) if sport_ids is not None else live_sport_ids()
        self.snapshot_at = None
        self.session_id = session_id

    def apply_message(self, message):
        if not isinstance(message, dict):
            raise LiveMessageError("Live message must be an object")
        kind = message.get("type")
        result = {"type": kind, "updated": 0, "skipped": 0, "refresh_ids": []}
        if kind == "pong":
            return result
        if self.session_id and not is_ws_session_active(self.session_id):
            return {**result, "skipped": 1}
        if kind == "live.snapshot":
            # Validate the entire snapshot before changing data or marking absences.
            observed_at, states = validate_snapshot(message)
            if self.snapshot_at and observed_at <= self.snapshot_at:
                return {**result, "skipped": len(states)}
            states = [state for state in states if state["sport_pk"] in self.sport_ids]
            ids = [state["game_pk"] for state in states]
            ordering = Q()
            if not self.session_id or self.snapshot_at is not None:
                ordering = Q(live_state_updated_at__lte=observed_at) | Q(live_state_updated_at__isnull=True)
            missing = Match.objects.filter(
                ordering,
                provider=Provider.NEUROKEFF, sync_scope=Match.SyncScope.LIVE,
                sport__external_id__in=self.sport_ids,
            ).exclude(external_id__in=ids)
            # Absence is not a final score/status. Request exact REST records.
            result["refresh_ids"].extend(missing.values_list("external_id", flat=True))
            missing.update(live_state_needs_refresh=True)
            self.snapshot_at = observed_at
        elif kind in {"match.entered_live", "match.updated", "match.status_changed"}:
            observed_at = _timestamp(message.get("occurred_at"))
            state = validate_match(message.get("match"))
            if message.get("game_pk", state["game_pk"]) != state["game_pk"] or message.get("status", state["status"]) != state["status"]:
                raise LiveMessageError("Conflicting match identity/status")
            states = [state] if state["sport_pk"] in self.sport_ids else []
        elif kind == "match.removed":
            observed_at = _timestamp(message.get("occurred_at"))
            if not _positive_id(message.get("game_pk")):
                raise LiveMessageError("Invalid removed match PK")
            return self._remove(message["game_pk"], observed_at, result)
        else:
            raise LiveMessageError("Unsupported live message type")
        for state in states:
            status = self._apply_state(state, observed_at, kind)
            if status == "refresh":
                result["refresh_ids"].append(state["game_pk"])
            elif status == "updated":
                result["updated"] += 1
                if state["status"] == "2":
                    result["refresh_ids"].append(state["game_pk"])
            else:
                result["skipped"] += 1
        result["refresh_ids"] = sorted(set(result["refresh_ids"]))
        return result

    def _is_newer_state(self, match, observed_at):
        if not self.session_id:
            return not match.live_state_updated_at or observed_at > match.live_state_updated_at
        if not is_ws_session_active(self.session_id):
            return False
        raw = match.raw_data if isinstance(match.raw_data, dict) else {}
        previous = raw.get("live_stream")
        # A new session takes over from REST; duplicates within that session
        # are ordered by the last WS message, including removals.
        return not isinstance(previous, dict) or previous.get("session_id") != self.session_id or (
            observed_at > _timestamp(previous.get("observed_at"))
        )

    @transaction.atomic
    def _apply_state(self, state, observed_at, kind):
        # REST Game.id is already stored in external_id; never use a supplier's ID.
        match = Match.objects.select_for_update(of=("self",)).select_related(
            "sport", "home_team", "away_team",
        ).filter(provider=Provider.NEUROKEFF, external_id=state["game_pk"]).first()
        if match is None:
            return "refresh"  # WS has no names/league/date: bootstrap via REST once.
        if not self._is_newer_state(match, observed_at):
            return "skipped"
        if match.sport is None or match.sport.external_id != state["sport_pk"]:
            return "refresh"
        for side in ("home", "away"):
            team = getattr(match, f"{side}_team")
            if team is None or team.external_id != state[f"{side}_team_pk"]:
                return "refresh"
        scope = MatchSyncService._scope_from_status(state["status"])
        if match.sync_scope == Match.SyncScope.FINISHED and scope != Match.SyncScope.FINISHED:
            return "skipped"
        clock = state.get("clock") or {}
        score = state["score"]
        raw = dict(match.raw_data or {})
        raw.update(time_status=state["status"], live_minute=clock.get("minute"),
                   live_minute_str=clock.get("display") or "", clock=state.get("clock"),
                   period=state.get("period"), point=state.get("point"),
                   serving_team_pk=state.get("serving_team_pk"))
        # Keep the full native object; adapt score mappings to existing readers.
        raw["live_stream"] = {"observed_at": observed_at.isoformat(), "type": kind, "match": state,
                              "session_id": self.session_id}
        raw["periods"] = {key: f"{value['home']}-{value['away']}"
                          if isinstance(value, dict) and type(value.get("home")) is int and type(value.get("away")) is int
                          else value for key, value in state["periods"].items()}
        if match.sport.code == "football":
            raw["first_time_score"] = raw["periods"].get("first") or ""
            raw.pop("first_half_score", None)
            raw.pop("ht_score", None)
        updates = {"sync_scope": scope, "time_status": state["status"],
                   "live_minute": clock.get("minute"), "live_minute_label": clock.get("display") or "",
                   "raw_data": raw, "live_state_updated_at": observed_at, "live_state_needs_refresh": state["status"] == "2",
                   "last_seen_at": timezone.now(), "updated_at": timezone.now()}
        # Missing final scores must never cause settlement using an old live score.
        updates["score"] = raw["score"] = (
            f"{score['home']}-{score['away']}" if score["home"] is not None and score["away"] is not None else ""
        )
        Match.objects.filter(pk=match.pk).update(**updates)
        return "updated"

    @transaction.atomic
    def _remove(self, game_id, observed_at, result):
        match = Match.objects.select_for_update(of=("self",)).filter(
            provider=Provider.NEUROKEFF, external_id=game_id, sport__external_id__in=self.sport_ids,
        ).first()
        if match is None or not self._is_newer_state(match, observed_at):
            return {**result, "skipped": 1}
        if match.sync_scope in {Match.SyncScope.LIVE, Match.SyncScope.CONNECTION_LOST}:
            # Removed upstream is NOT a completed match, and must not void bets.
            raw = dict(match.raw_data or {})
            previous = raw.get("live_stream")
            raw["live_stream"] = {
                **(previous if isinstance(previous, dict) else {}),
                "observed_at": observed_at.isoformat(), "type": "match.removed", "session_id": self.session_id,
            }
            Match.objects.filter(pk=match.pk).update(
                sync_scope=Match.SyncScope.CONNECTION_LOST, live_state_needs_refresh=True,
                live_state_updated_at=observed_at, updated_at=timezone.now(), raw_data=raw,
            )
            result["updated"] = 1
            result["refresh_ids"] = [game_id]
        return result
