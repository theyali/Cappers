import io
import json
from datetime import timedelta
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from game import tasks
from game.management.commands.run_neurokeff_live import monitor_connection, queue_reconciliation, websocket_url
from game.models import Match, MatchEvent, MatchOdds, MatchStatistic, Sport, Team
from game.services.live_stream import LiveMessageError, LiveStateStream
from game.services.live_stream_health import LiveStreamHealth, has_ws_priority, is_ws_session_active
from game.services.match_sync import MatchSyncService
from game.services.settlement import VOID_MATCH_SCOPES, _first_half_score


def state(**changes):
    return {
        "game_pk": 501, "sport_pk": 2, "home_team_pk": 10, "away_team_pk": 20,
        "score": {"home": 1, "away": 0}, "status": "1",
        "clock": {"minute": 47, "second": None, "display": "45+2"},
        "period": {"code": "second_half", "number": 2, "name": "Second Half", "provider_status": "2H"},
        "periods": {"first": {"home": 0, "away": 0}}, "point": None, "serving_team_pk": None,
        **changes,
    }


def message(payload=None, *, kind="match.updated", at=None):
    return {"type": kind, "event_id": "duplicate-id-is-not-an-ordering-key",
            "occurred_at": (at or timezone.now()).isoformat(), "match": payload or state()}


def snapshot(states, at=None):
    return {"type": "live.snapshot", "generated_at": (at or timezone.now()).isoformat(), "matches": states}


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class LiveStreamTests(TestCase):
    def setUp(self):
        cache.clear()
        self.sport = Sport.objects.create(external_id=2, code="football", name="Football")
        self.home = Team.objects.create(external_id=10, sport=self.sport, name="Home")
        self.away = Team.objects.create(external_id=20, sport=self.sport, name="Away")
        self.match = Match.objects.create(
            external_id=501, sport=self.sport, home_team=self.home, away_team=self.away,
            sync_scope=Match.SyncScope.LIVE, score="0-0", time_status="1",
            raw_data={"events": {"sentinel": 1}, "statistics": {"sentinel": 2}, "odds": {"sentinel": 3}},
        )
        self.stream = LiveStateStream(sport_ids={2})

    def apply(self, payload=None, **kwargs):
        result = self.stream.apply_message(message(payload, **kwargs))
        self.match.refresh_from_db()
        return result

    def test_updates_state_without_touching_statistics_events_or_odds(self):
        event = MatchEvent.objects.create(match=self.match, event_key="goal", minute=15)
        statistic = MatchStatistic.objects.create(match=self.match, stat_code="shots", home_value=5)
        odds = MatchOdds.objects.create(match=self.match, home_win_bet=1.9)
        before = [list(model.objects.values()) for model in (MatchEvent, MatchStatistic, MatchOdds)]

        result = self.apply()

        self.assertEqual(result["updated"], 1)
        self.assertEqual((self.match.score, self.match.live_minute, self.match.live_minute_label), ("1-0", 47, "45+2"))
        self.assertEqual(self.match.raw_data["live_stream"]["match"], state())
        self.assertEqual(_first_half_score(self.match), (0, 0))
        for key, value in (("events", 1), ("statistics", 2), ("odds", 3)):
            self.assertEqual(self.match.raw_data[key], {"sentinel": value})
        self.assertEqual(before, [list(model.objects.values()) for model in (MatchEvent, MatchStatistic, MatchOdds)])
        self.assertTrue(event.pk and statistic.pk and odds.pk)

    def test_all_documented_statuses(self):
        expected = [Match.SyncScope.PREMATCH, Match.SyncScope.LIVE, Match.SyncScope.CONNECTION_LOST,
                    Match.SyncScope.FINISHED, Match.SyncScope.POSTPONED, Match.SyncScope.CANCELED,
                    Match.SyncScope.FORFEIT, Match.SyncScope.INTERRUPTED, Match.SyncScope.ABANDONED]
        for code, scope in enumerate(expected):
            with self.subTest(code=code):
                Match.objects.filter(pk=self.match.pk).update(sync_scope=Match.SyncScope.LIVE)
                self.apply(state(status=str(code)), kind="match.status_changed")
                self.assertEqual(self.match.sync_scope, scope)
        self.assertNotIn(Match.SyncScope.CONNECTION_LOST, VOID_MATCH_SCOPES)

    def test_duplicates_and_older_messages_do_not_roll_back_state(self):
        stamp = timezone.now() - timedelta(seconds=2)
        self.apply(state(score={"home": 2, "away": 1}), at=stamp)
        first_updated = self.match.updated_at
        for at in (stamp, stamp - timedelta(seconds=1)):
            result = self.apply(state(score={"home": 0, "away": 0}), at=at)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(self.match.score, "2-1")
            self.assertEqual(self.match.updated_at, first_updated)
        # event_id is not a version: a later full message still applies.
        self.assertEqual(self.apply()["updated"], 1)

    def test_newer_snapshot_cannot_reopen_finished_match(self):
        self.apply(state(status="3"), kind="match.status_changed", at=timezone.now() - timedelta(seconds=1))
        result = self.stream.apply_message(snapshot([state()]))
        self.match.refresh_from_db()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.match.sync_scope, Match.SyncScope.FINISHED)

    def test_stale_snapshot_does_not_mark_newer_state_as_missing(self):
        stamp = timezone.now()
        self.apply(at=stamp)
        self.assertEqual(self.stream.apply_message(snapshot([], stamp - timedelta(seconds=1)))["refresh_ids"], [])
        self.match.refresh_from_db()
        self.assertFalse(self.match.live_state_needs_refresh)

    def test_snapshot_absence_requests_rest_without_finishing_or_deleting(self):
        result = self.stream.apply_message(snapshot([]))
        self.match.refresh_from_db()
        self.assertEqual(result["refresh_ids"], [501])
        self.assertTrue(self.match.live_state_needs_refresh)
        self.assertEqual(self.match.sync_scope, Match.SyncScope.LIVE)
        self.assertEqual(self.match.score, "0-0")

    def test_removed_marks_connection_lost_and_requests_rest_but_does_not_void(self):
        result = self.stream.apply_message({"type": "match.removed", "game_pk": 501,
                                           "occurred_at": timezone.now().isoformat()})
        self.match.refresh_from_db()
        self.assertEqual(result["refresh_ids"], [501])
        self.assertEqual(self.match.sync_scope, Match.SyncScope.CONNECTION_LOST)
        self.assertNotIn(self.match.sync_scope, VOID_MATCH_SCOPES)
        self.assertEqual(self.match.score, "0-0")
        self.assertTrue(self.match.live_state_needs_refresh)

    def test_removed_cannot_overwrite_finished_status(self):
        self.apply(state(status="3"))
        result = self.stream.apply_message({"type": "match.removed", "game_pk": 501,
                                           "occurred_at": timezone.now().isoformat()})
        self.match.refresh_from_db()
        self.assertEqual(self.match.sync_scope, Match.SyncScope.FINISHED)
        self.assertEqual(result["refresh_ids"], [])

    def test_unknown_match_is_bootstrapped_by_rest_not_created_without_metadata(self):
        result = self.stream.apply_message(snapshot([state(game_pk=999)]))
        self.assertIn(999, result["refresh_ids"])
        self.assertFalse(Match.objects.filter(external_id=999).exists())

    def test_mismatched_team_identity_requests_rest(self):
        result = self.apply(state(home_team_pk=999))
        self.assertEqual(result["refresh_ids"], [501])
        self.assertEqual(self.match.score, "0-0")

    def test_other_sports_are_not_updated(self):
        result = self.apply(state(sport_pk=3))
        self.assertEqual(result["updated"], 0)
        self.assertEqual(self.match.score, "0-0")

    def test_null_clock_clears_old_minute_and_zero_score_is_not_empty(self):
        self.apply()
        self.apply(state(clock=None, score={"home": 0, "away": 0}))
        self.assertIsNone(self.match.live_minute)
        self.assertEqual(self.match.live_minute_label, "")
        self.assertEqual(self.match.score, "0-0")

    def test_null_final_score_does_not_leave_old_live_score_for_settlement(self):
        self.apply(state(status="3", score={"home": None, "away": None}, clock=None))
        self.assertEqual(self.match.sync_scope, Match.SyncScope.FINISHED)
        self.assertEqual(self.match.score, "")

    def test_native_tennis_periods_points_and_serving_are_preserved(self):
        payload = state(periods={"S1": "6-3", "S2": "1-2"}, point="40-15", serving_team_pk=10)
        self.apply(payload)
        self.assertEqual(self.match.raw_data["periods"], payload["periods"])
        self.assertEqual(self.match.raw_data["point"], "40-15")
        self.assertEqual(self.match.raw_data["serving_team_pk"], 10)

    def test_malformed_snapshot_is_rejected_before_any_writes(self):
        for invalid in (state(status="3"), state(score={"home": -1, "away": 0}),
                        state(game_pk=True), state(clock={"minute": "47"}), state(periods=[])):
            with self.subTest(payload=invalid), self.assertRaises(LiveMessageError):
                self.stream.apply_message(snapshot([state(game_pk=999), invalid]))
            self.match.refresh_from_db()
            self.assertFalse(self.match.live_state_needs_refresh)
            self.assertIsNone(self.match.live_state_updated_at)

    def test_duplicate_snapshot_pk_and_untrusted_timestamps_are_rejected(self):
        for invalid in (snapshot([state(), state()]),
                        {**snapshot([]), "generated_at": "2026-01-01T00:00:00"},
                        snapshot([], timezone.now() + timedelta(hours=1))):
            with self.assertRaises(LiveMessageError):
                self.stream.apply_message(invalid)

    def test_rest_in_flight_cannot_overwrite_newer_websocket_state(self):
        older = timezone.now() - timedelta(seconds=5)
        self.apply(state(status="3", score={"home": 2, "away": 1}))
        result = MatchSyncService(provider=Mock())._sync_scope(
            Match.SyncScope.LIVE, [{"id": 501, "time_status": "1", "score": "0-0"}],
            derive_scope_from_payload=True, observed_at=older, state_only=True,
        )
        self.match.refresh_from_db()
        self.assertEqual((self.match.sync_scope, self.match.score), (Match.SyncScope.FINISHED, "2-1"))
        self.assertEqual(self.match.raw_data["score"], "2-1")
        self.assertEqual(self.match.raw_data["first_time_score"], "0-0")
        self.assertEqual(result["scopes"], {Match.SyncScope.FINISHED: 1})

    def test_targeted_rest_reconciliation_does_not_sync_addons(self):
        provider = Mock()
        provider.fetch_matches_info.return_value = [
            {"id": 501, "time_status": "3", "score": "2-1", "events": {"items": []}, "odds": {"home": 100}},
            {"id": 999, "time_status": "1"},  # Unrequested record must be ignored.
        ]
        service = MatchSyncService(provider=provider)
        with (patch.object(service, "_sync_odds") as odds, patch.object(service, "_sync_embedded_events") as events,
              patch.object(service, "_sync_embedded_statistics") as statistics):
            service.sync_match_states([501])
        odds.assert_not_called()
        events.assert_not_called()
        statistics.assert_not_called()
        self.match.refresh_from_db()
        self.assertEqual(self.match.sync_scope, Match.SyncScope.FINISHED)
        self.assertEqual(self.match.raw_data["odds"], {"sentinel": 3})
        self.assertFalse(Match.objects.filter(external_id=999).exists())

    def test_connection_lost_is_still_eligible_for_stuck_recovery(self):
        Match.objects.filter(pk=self.match.pk).update(sync_scope=Match.SyncScope.CONNECTION_LOST,
                                                     last_seen_at=timezone.now() - timedelta(hours=1))
        provider = Mock()
        provider.fetch_matches_info.return_value = [{"id": 501, "time_status": "3", "score": "2-1"}]
        MatchSyncService(provider=provider).sync_stuck_live_matches()
        provider.fetch_matches_info.assert_called_once_with([501])
        self.match.refresh_from_db()
        self.assertEqual(self.match.sync_scope, Match.SyncScope.FINISHED)

    def test_passed_kickoff_does_not_automatically_make_prematch_live(self):
        Match.objects.filter(pk=self.match.pk).update(
            sync_scope=Match.SyncScope.PREMATCH, time_status="0", starts_at=timezone.now() - timedelta(hours=1),
        )
        service = MatchSyncService(provider=Mock())
        self.assertEqual(service._flag_due_prematches(), 1)
        self.match.refresh_from_db()
        self.assertEqual(self.match.sync_scope, Match.SyncScope.PREMATCH)
        self.assertEqual(self.match.time_status, "0")
        self.assertTrue(self.match.live_state_needs_refresh)
        self.assertEqual(service._flag_due_prematches(), 0)

    def start_ws(self):
        health = LiveStreamHealth()
        health.mark_alive()
        self.stream = LiveStateStream(sport_ids={2}, session_id=health.session_id)
        self.apply(at=timezone.now() - timedelta(seconds=10))
        return health

    def rest_payload(self, **changes):
        return {
            "id": 501, "sport_id": 2, "time_status": "1", "score": "0-0",
            "teams": {"home": {"id": 10, "name": "Home"}, "away": {"id": 20, "name": "Away"}},
            "live_minute": 1, "live_minute_str": "1", "clock": None, "periods": {},
            "point": "0-0", "period": None, "serving_team_pk": None, **changes,
        }

    def test_later_rest_live_request_cannot_overwrite_any_ws_fields(self):
        self.start_ws()
        previous = {field: getattr(self.match, field) for field in MatchSyncService.LIVE_STATE_FIELDS}
        previous_raw = {key: self.match.raw_data.get(key) for key in MatchSyncService.LIVE_RAW_KEYS}
        stamp = self.match.live_state_updated_at
        provider = Mock()
        provider.fetch_live_matches.return_value = [self.rest_payload(time_status="3")]
        service = MatchSyncService(provider=provider)
        with (patch.object(service, "_sync_odds") as odds,
              patch.object(service, "_sync_embedded_statistics") as statistics,
              patch.object(service, "_sync_embedded_events") as events):
            service.sync_live()
        self.match.refresh_from_db()
        self.assertEqual(previous, {field: getattr(self.match, field) for field in previous})
        self.assertEqual(previous_raw, {key: self.match.raw_data.get(key) for key in previous_raw})
        self.assertEqual(self.match.live_state_updated_at, stamp)
        self.assertTrue(has_ws_priority(self.match))
        # Existing REST addon synchronizers continue to be called unchanged.
        for sync in (odds, statistics, events):
            sync.assert_called_once()

    def test_other_rest_paths_cannot_bypass_active_ws_ownership(self):
        self.start_ws()
        provider = Mock()
        provider.fetch_matches_info.return_value = [self.rest_payload(time_status="3")]
        provider.fetch_finished_matches.return_value = provider.fetch_matches_info.return_value
        service = MatchSyncService(provider=provider)
        service.sync_finished()
        service.sync_match_states([501])
        Match.objects.filter(pk=self.match.pk).update(last_seen_at=timezone.now() - timedelta(hours=1))
        service.sync_stuck_live_matches()
        self.match.refresh_from_db()
        self.assertEqual((self.match.sync_scope, self.match.score), (Match.SyncScope.LIVE, "1-0"))
        self.assertTrue(has_ws_priority(self.match))

    def test_disconnect_or_health_expiry_allows_rest_fallback(self):
        for mode in ("disconnect", "expire"):
            with self.subTest(mode=mode):
                health = self.start_ws()
                if mode == "disconnect":
                    health.clear()
                else:
                    cache.set(f"live-ws:health:{health.session_id}", True, timeout=-1)
                provider = Mock()
                provider.fetch_live_matches.return_value = [self.rest_payload(score="2-0")]
                MatchSyncService(provider=provider).sync_live()
                self.match.refresh_from_db()
                self.assertEqual(self.match.score, "2-0")
                self.assertEqual(self.match.live_minute, 1)
                self.assertFalse(has_ws_priority(self.match))

    def test_reconnect_snapshot_takes_over_newer_local_rest_timestamp(self):
        self.start_ws().clear()
        provider = Mock()
        provider.fetch_live_matches.return_value = [self.rest_payload(score="2-0")]
        MatchSyncService(provider=provider).sync_live()
        self.match.refresh_from_db()
        rest_stamp = self.match.live_state_updated_at
        health = LiveStreamHealth()
        health.mark_alive()
        self.stream = LiveStateStream(sport_ids={2}, session_id=health.session_id)
        self.stream.apply_message(snapshot([state(score={"home": 3, "away": 0})], rest_stamp - timedelta(seconds=1)))
        self.match.refresh_from_db()
        self.assertEqual(self.match.score, "3-0")
        self.assertTrue(has_ws_priority(self.match))
        MatchSyncService(provider=provider).sync_live()
        self.match.refresh_from_db()
        self.assertEqual(self.match.score, "3-0")

    def test_removed_match_can_be_reconciled_while_socket_is_healthy(self):
        self.start_ws()
        self.stream.apply_message({"type": "match.removed", "game_pk": 501, "occurred_at": timezone.now().isoformat()})
        provider = Mock()
        provider.fetch_matches_info.return_value = [self.rest_payload(time_status="3", score="2-1")]
        MatchSyncService(provider=provider).sync_match_states([501])
        self.match.refresh_from_db()
        self.assertEqual((self.match.sync_scope, self.match.score), (Match.SyncScope.FINISHED, "2-1"))
        self.assertFalse(has_ws_priority(self.match))

    def test_old_removed_message_cannot_release_reentered_match(self):
        self.start_ws()
        stamp = timezone.now() - timedelta(seconds=1)
        self.apply(kind="match.entered_live", at=stamp)
        result = self.stream.apply_message({"type": "match.removed", "game_pk": 501,
                                           "occurred_at": (stamp - timedelta(seconds=1)).isoformat()})
        self.match.refresh_from_db()
        self.assertEqual(result["skipped"], 1)
        self.assertTrue(has_ws_priority(self.match))

    def test_queued_reconciliation_cannot_overwrite_a_reentered_ws_match(self):
        self.start_ws()
        self.stream.apply_message({"type": "match.removed", "game_pk": 501,
                                   "occurred_at": (timezone.now() - timedelta(seconds=2)).isoformat()})

        def fetch(ids):
            self.apply(state(score={"home": 2, "away": 0}), kind="match.entered_live",
                       at=timezone.now() - timedelta(seconds=1))
            return [self.rest_payload(time_status="3", score="1-0")]

        provider = Mock()
        provider.fetch_matches_info.side_effect = fetch
        MatchSyncService(provider=provider).sync_match_states([501])
        self.match.refresh_from_db()
        self.assertEqual((self.match.sync_scope, self.match.score), (Match.SyncScope.LIVE, "2-0"))
        self.assertTrue(has_ws_priority(self.match))

    def test_old_ws_update_cannot_undo_removal(self):
        self.start_ws()
        stamp = timezone.now() - timedelta(seconds=1)
        self.stream.apply_message({"type": "match.removed", "game_pk": 501, "occurred_at": stamp.isoformat()})
        result = self.apply(at=stamp - timedelta(seconds=1))
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.match.sync_scope, Match.SyncScope.CONNECTION_LOST)
        self.assertFalse(has_ws_priority(self.match))

    def test_inactive_consumer_cannot_apply_updates_after_rest_takes_over(self):
        self.start_ws().clear()
        result = self.apply(state(score={"home": 5, "away": 0}))
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.match.score, "1-0")

    def test_missing_match_in_new_snapshot_releases_previous_session_ownership(self):
        self.start_ws().clear()
        health = LiveStreamHealth()
        health.mark_alive()
        self.stream = LiveStateStream(sport_ids={2}, session_id=health.session_id)
        self.assertEqual(self.stream.apply_message(snapshot([]))["refresh_ids"], [501])
        provider = Mock()
        provider.fetch_matches_info.return_value = [self.rest_payload(time_status="3", score="2-1")]
        MatchSyncService(provider=provider).sync_match_states([501])
        self.match.refresh_from_db()
        self.assertEqual(self.match.sync_scope, Match.SyncScope.FINISHED)

    def test_unmanaged_match_is_still_updated_via_rest(self):
        health = LiveStreamHealth()
        health.mark_alive()
        provider = Mock()
        provider.fetch_live_matches.return_value = [self.rest_payload(score="2-0")]
        MatchSyncService(provider=provider).sync_live()
        self.match.refresh_from_db()
        self.assertEqual(self.match.score, "2-0")
        self.assertFalse(has_ws_priority(self.match))

    def test_scout_connection_lost_releases_priority_and_requests_reconciliation(self):
        self.start_ws()
        result = self.apply(state(status="2"), kind="match.status_changed")
        self.assertEqual(result["refresh_ids"], [501])
        self.assertFalse(has_ws_priority(self.match))

    def test_health_cache_failure_keeps_rest_fallback_available(self):
        self.start_ws()
        with patch("game.services.live_stream_health.cache.get", side_effect=ConnectionError("unavailable")):
            self.assertFalse(has_ws_priority(self.match))

    def test_first_snapshot_absence_uses_ws_not_later_local_rest_time(self):
        Match.objects.filter(pk=self.match.pk).update(live_state_updated_at=timezone.now())
        health = LiveStreamHealth()
        health.mark_alive()
        stream = LiveStateStream(sport_ids={2}, session_id=health.session_id)
        self.assertEqual(stream.apply_message(snapshot([], timezone.now() - timedelta(seconds=1)))["refresh_ids"], [501])


@override_settings(NEUROKEFF_API_TOKEN="test-secret", NEUROKEFF_LIVE_WS_SPORTS=[2],
                   NEUROKEFF_LIVE_WS_URL="wss://sports.api-neurokeff.ru/ws/v1/live/",
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class LiveCommandTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_url_uses_pk_filter_and_does_not_expose_token(self):
        self.assertEqual(websocket_url(), "wss://sports.api-neurokeff.ru/ws/v1/live/?sport=2")
        for invalid in ("ws://example.com/live/", "wss://example.com/live/?token=secret"):
            with override_settings(NEUROKEFF_LIVE_WS_URL=invalid), self.assertRaises(CommandError):
                websocket_url()

    def test_check_validates_snapshot_without_database_or_celery_writes(self):
        out = io.StringIO()
        with (patch("game.management.commands.run_neurokeff_live.connect") as connect,
              patch("game.management.commands.run_neurokeff_live.Redis") as redis,
              patch("game.management.commands.run_neurokeff_live.LiveStreamHealth") as health,
              patch("game.management.commands.run_neurokeff_live.queue_reconciliation") as queue):
            connect.return_value.__enter__.return_value.recv.return_value = json.dumps(snapshot([state()]))
            call_command("run_neurokeff_live", "--check", stdout=out)
        self.assertIn("Valid live snapshot: 1", out.getvalue())
        self.assertEqual(connect.call_args.kwargs["additional_headers"], {"Authorization": "Token test-secret"})
        self.assertEqual(connect.call_args.kwargs["ping_interval"], 20)
        redis.from_url.assert_not_called()
        queue.assert_not_called()
        health.return_value.mark_alive.assert_not_called()
        health.return_value.clear.assert_not_called()

    def test_check_failure_redacts_exception_text(self):
        with patch("game.management.commands.run_neurokeff_live.connect", side_effect=RuntimeError("test-secret")):
            with self.assertRaises(CommandError) as caught:
                call_command("run_neurokeff_live", "--check")
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertIn("RuntimeError", str(caught.exception))

    def test_check_rejects_connection_without_protocol_pong(self):
        with patch("game.management.commands.run_neurokeff_live.connect") as connect:
            socket = connect.return_value.__enter__.return_value
            socket.recv.return_value = json.dumps(snapshot([]))
            socket.ping.return_value.wait.return_value = False
            with self.assertRaisesMessage(CommandError, "LiveMessageError"):
                call_command("run_neurokeff_live", "--check", stdout=io.StringIO())

    def test_second_consumer_does_not_connect_or_release_another_lease(self):
        with (patch("game.management.commands.run_neurokeff_live.Redis") as redis,
              patch("game.management.commands.run_neurokeff_live.connect") as connect):
            lease = redis.from_url.return_value.lock.return_value
            lease.acquire.return_value = False
            with self.assertRaisesMessage(CommandError, "already owns"):
                call_command("run_neurokeff_live")
            lease.release.assert_not_called()
            connect.assert_not_called()

    def test_listener_applies_messages_and_queues_only_state_reconciliation(self):
        with (patch("game.management.commands.run_neurokeff_live.Redis") as redis,
              patch("game.management.commands.run_neurokeff_live.connect") as connect,
              patch("game.management.commands.run_neurokeff_live.LiveStateStream") as stream,
              patch("game.management.commands.run_neurokeff_live.queue_reconciliation") as queue):
            stream.return_value.apply_message.side_effect = [
                {"updated": 1, "refresh_ids": [999]}, {"updated": 1, "refresh_ids": []},
            ]
            initial, update = snapshot([state()]), message(state(status="3"), kind="match.status_changed")
            connect.return_value.__enter__.return_value.recv.side_effect = [
                json.dumps(initial), json.dumps(update), KeyboardInterrupt(),
            ]
            with self.assertRaises(KeyboardInterrupt):
                call_command("run_neurokeff_live", stdout=io.StringIO())
            self.assertEqual(stream.return_value.apply_message.call_count, 2)
            self.assertEqual(stream.return_value.apply_message.call_args.args[0], update)
            queue.assert_called_once_with([999])
            redis.from_url.return_value.lock.return_value.release.assert_called_once_with()

    def test_transport_error_reconnects_but_auth_failure_stops_and_releases_lease(self):
        auth_error = RuntimeError("test-secret")
        auth_error.response = Mock(status_code=403)
        err = io.StringIO()
        with (patch("game.management.commands.run_neurokeff_live.Redis") as redis,
              patch("game.management.commands.run_neurokeff_live.random.uniform", return_value=0),
              patch("game.management.commands.run_neurokeff_live.connect", side_effect=[OSError(), auth_error]) as connect):
            with self.assertRaisesMessage(CommandError, "http=403"):
                call_command("run_neurokeff_live", stderr=err)
            self.assertEqual(connect.call_count, 2)
            redis.from_url.return_value.lock.return_value.release.assert_called_once_with()
        self.assertIn("reconnecting", err.getvalue())
        self.assertNotIn("test-secret", err.getvalue())

    def test_reconciliation_queue_is_deduplicated_and_retries_after_broker_error(self):
        with patch.object(tasks.refresh_live_match_states, "apply_async") as queue:
            queue_reconciliation([501, 501])
            queue_reconciliation([501])
            queue.assert_called_once_with(args=[[501]], retry=False)
            queue.side_effect = RuntimeError("broker unavailable")
            with self.assertRaises(RuntimeError):
                queue_reconciliation([502])
            queue.side_effect = None
            queue_reconciliation([502])
            self.assertEqual(queue.call_count, 3)

    def test_reconciliation_task_validates_ids_and_uses_state_only_service(self):
        with patch("game.tasks.MatchSyncService") as service:
            tasks.refresh_live_match_states([501, True, "502", 0, -1, 501])
            service.return_value.sync_match_states.assert_called_once_with([501])
        self.assertEqual(tasks.refresh_live_match_states([])["reason"], "empty_ids")

    def test_large_reconciliation_is_split_into_bounded_tasks(self):
        with patch.object(tasks.refresh_live_match_states, "apply_async") as queue:
            queue_reconciliation(list(range(1000, 1101)))
        self.assertEqual([len(call.kwargs["args"][0]) for call in queue.call_args_list], [50, 50, 1])

    def test_only_live_rest_schedule_is_changed_to_one_minute(self):
        for sport in ("football", "tennis", "basketball", "hockey"):
            self.assertEqual(settings.CELERY_BEAT_SCHEDULE[f"fetch-live-{sport}-matches"]["schedule"], timedelta(minutes=1))

    def test_heartbeat_renews_only_after_confirmed_pong(self):
        socket, health, stopped = Mock(), Mock(), Mock()
        stopped.wait.side_effect = [False, True]
        stopped.is_set.return_value = False
        socket.ping.return_value.wait.return_value = True
        monitor_connection(socket, health, stopped)
        socket.ping.return_value.wait.assert_called_once_with(timeout=5)
        health.mark_alive.assert_called_once_with()

    def test_missing_pong_releases_priority_and_closes_connection(self):
        socket, health, stopped = Mock(), Mock(), Mock()
        stopped.wait.return_value = False
        socket.ping.return_value.wait.return_value = False
        monitor_connection(socket, health, stopped)
        health.mark_alive.assert_not_called()
        health.clear.assert_called()
        stopped.set.assert_called_once_with()
        socket.close.assert_called_once_with()

    def test_stopped_consumer_cannot_renew_health(self):
        socket, health, stopped, consumer_stopped = Mock(), Mock(), Mock(), Mock()
        stopped.wait.return_value = False
        consumer_stopped.is_set.return_value = True
        monitor_connection(socket, health, stopped, consumer_stopped)
        socket.ping.assert_not_called()
        health.mark_alive.assert_not_called()
        health.clear.assert_called()

    def test_closed_session_does_not_clear_another_session_health(self):
        first, second = LiveStreamHealth(), LiveStreamHealth()
        first.mark_alive()
        second.mark_alive()
        first.clear()
        self.assertFalse(is_ws_session_active(first.session_id))
        self.assertTrue(is_ws_session_active(second.session_id))

    def test_stalled_feed_releases_priority_even_if_socket_does_not_disconnect(self):
        auth_error = RuntimeError()
        auth_error.response = Mock(status_code=403)
        with (patch("game.management.commands.run_neurokeff_live.Redis"),
              patch("game.management.commands.run_neurokeff_live.LiveStateStream") as stream,
              patch("game.management.commands.run_neurokeff_live.LiveStreamHealth") as health,
              patch("game.management.commands.run_neurokeff_live.time.monotonic", return_value=0) as clock,
              patch("game.management.commands.run_neurokeff_live.random.uniform", return_value=0),
              patch("game.management.commands.run_neurokeff_live.connect") as connect):
            context = Mock()
            context.__enter__ = Mock(return_value=Mock())
            context.__exit__ = Mock(return_value=False)
            connect.side_effect = [context, auth_error]
            stream.return_value.apply_message.return_value = {"updated": 0, "refresh_ids": []}
            calls = []

            def receive(**kwargs):
                calls.append(1)
                if len(calls) == 1:
                    return json.dumps(snapshot([]))
                clock.return_value = 91
                raise TimeoutError()

            context.__enter__.return_value.recv.side_effect = receive
            with self.assertRaisesMessage(CommandError, "http=403"):
                call_command("run_neurokeff_live", stdout=io.StringIO(), stderr=io.StringIO())
            self.assertEqual(connect.call_count, 2)
            self.assertEqual(len(calls), 2)
            health.return_value.mark_alive.assert_called_once_with()
            health.return_value.clear.assert_called()
