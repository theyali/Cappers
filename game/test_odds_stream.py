import io
from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from game.management.commands.run_neurokeff_odds import websocket_url
from game.models import Match, MatchBookmakerOdds, MatchOdds, MatchOddsSnapshot, Sport
from game.services.match_sync import MatchSyncService
from game.services.odds_stream import (
    OddsMessageError,
    odds_sport_ids,
    queue_odds_message,
    queue_prematch_reconciliation,
    queue_match_odds_refresh,
    queue_missing_prematch_odds,
    validate_odds_message,
)
from game.tasks import _fetch_upcoming_for_sport, reconcile_prematch_odds, refresh_prematch_match_odds


def notification(**changes):
    return {"type": "prematch.odds.available", "event_id": str(uuid4()),
            "occurred_at": timezone.now().isoformat(), "game_pk": 501,
            "sport_pk": 2, "bookmaker_pk": 7, "phase": "prematch", **changes}


ODDS_SETTINGS = {
    "NEUROKEFF_ODDS_WS_SPORTS": [],
    "NEUROKEFF_SPORTS": [{"id": 2, "code": "football"}, {"id": 3, "code": "hockey"}],
    "CACHES": {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
}


@override_settings(**ODDS_SETTINGS)
class OddsNotificationTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_validates_identity_phase_uuid_and_timestamp(self):
        validate_odds_message(notification())
        validate_odds_message(notification(type="prematch.odds.updated", changed=["markets", "short"]))
        validate_odds_message(notification(type="prematch.odds.updated", bookmaker_pk=None))
        bad_values = [{"game_pk": True}, {"game_pk": "501"}, {"sport_pk": 0},
                      {"bookmaker_pk": -1}, {"phase": "live"}, {"event_id": "bad"},
                      {"type": "live.odds.updated"}, {"type": []}, {"changed": "short"}, {"changed": [1]},
                      {"occurred_at": "2026-10-17T08:00:00"}, {"occurred_at": None},
                      {"occurred_at": (timezone.now() + timedelta(minutes=2)).isoformat()}]
        for changes in bad_values:
            with self.subTest(changes=changes), self.assertRaises(OddsMessageError):
                validate_odds_message(notification(**changes))

    @patch("game.tasks.refresh_prematch_match_odds.apply_async")
    def test_queues_provider_game_pk_and_sport_not_bookmaker_or_prices(self, enqueue):
        message = notification()
        self.assertTrue(queue_odds_message(message, {2}))
        enqueue.assert_called_once_with(args=[501, 2, "prematch.odds.available"], retry=False)
        self.assertFalse(queue_odds_message(message, {2}))
        self.assertFalse(queue_odds_message(message, {2}))
        self.assertEqual(enqueue.call_count, 1)

    @patch("game.tasks.refresh_prematch_match_odds.apply_async")
    def test_distinct_events_for_same_game_are_not_throttled_and_other_sports_are_ignored(self, enqueue):
        self.assertFalse(queue_odds_message(notification(sport_pk=3), {2}))
        self.assertTrue(queue_odds_message(notification(), {2}))
        update = notification(type="prematch.odds.updated", changed=["markets", "short"])
        self.assertTrue(queue_odds_message(update, {2}))
        self.assertFalse(queue_odds_message(update, {2}))
        self.assertTrue(queue_odds_message(notification(type="prematch.odds.updated", changed=["short"]), {2}))
        self.assertEqual(enqueue.call_count, 3)
        self.assertEqual(enqueue.call_args.kwargs["args"], [501, 2, "prematch.odds.updated"])

    @patch("game.tasks.refresh_prematch_match_odds.apply_async", side_effect=RuntimeError("broker down"))
    def test_failed_enqueue_does_not_consume_notification(self, enqueue):
        message = notification()
        with self.assertRaises(RuntimeError):
            queue_odds_message(message, {2})
        self.assertIsNone(cache.get(f"odds-ws:event:{message['event_id']}"))
        enqueue.side_effect = None
        self.assertTrue(queue_odds_message(message, {2}))

    @patch("game.tasks.reconcile_prematch_odds.apply_async")
    def test_rest_reconciliation_on_each_connection_is_storm_limited(self, enqueue):
        self.assertEqual(queue_prematch_reconciliation({2, 3}), 2)
        self.assertEqual(queue_prematch_reconciliation({2, 3}), 0)
        cache.clear()
        self.assertEqual(queue_prematch_reconciliation({2, 3}), 2)
        self.assertEqual(enqueue.call_count, 4)

    @patch("game.tasks.reconcile_prematch_odds.apply_async", side_effect=RuntimeError("broker down"))
    def test_failed_reconciliation_enqueue_can_be_retried(self, enqueue):
        with self.assertRaises(RuntimeError):
            queue_prematch_reconciliation({2})
        self.assertIsNone(cache.get("odds-ws:reconcile:2"))

    def test_sports_and_url_default_to_project_not_live_subset(self):
        with override_settings(NEUROKEFF_LIVE_WS_SPORTS=[2]):
            self.assertEqual(odds_sport_ids(), {2, 3})
        self.assertEqual(websocket_url({3, 2}), "wss://sports.api-neurokeff.ru/ws/v1/odds/?sport=2%2C3")
        with override_settings(NEUROKEFF_ODDS_WS_SPORTS=[99]), self.assertRaises(OddsMessageError):
            odds_sport_ids()
        for url in ("ws://example.test/", "wss://token@example.test/", "wss://example.test/?token=secret"):
            with override_settings(NEUROKEFF_ODDS_WS_URL=url), self.assertRaises(CommandError):
                websocket_url({2})

    @override_settings(NEUROKEFF_API_TOKEN="do-not-log-me")
    @patch("game.management.commands.run_neurokeff_odds.queue_prematch_reconciliation")
    @patch("game.management.commands.run_neurokeff_odds.Redis")
    @patch("game.management.commands.run_neurokeff_odds.connect")
    def test_check_only_handshake_and_pong_without_db_lease_or_tasks(self, connect, redis, reconcile):
        socket = connect.return_value.__enter__.return_value
        socket.ping.return_value.wait.return_value = True
        output = io.StringIO()
        call_command("run_neurokeff_odds", check=True, stdout=output)
        redis.assert_not_called()
        reconcile.assert_not_called()
        socket.recv.assert_not_called()
        self.assertIn("handshake/pong OK", output.getvalue())
        self.assertNotIn("do-not-log-me", output.getvalue())

    @override_settings(NEUROKEFF_API_TOKEN="do-not-log-me")
    @patch("game.management.commands.run_neurokeff_odds.threading.Thread")
    @patch("game.management.commands.run_neurokeff_odds.threading.Event")
    @patch("game.management.commands.run_neurokeff_odds.queue_odds_message")
    @patch("game.management.commands.run_neurokeff_odds.queue_prematch_reconciliation")
    @patch("game.management.commands.run_neurokeff_odds.Redis")
    @patch("game.management.commands.run_neurokeff_odds.connect")
    def test_quiet_channel_stays_connected_and_disconnect_reconciles_again(self, connect, redis, reconcile, queue, event, thread):
        stop, lost = Mock(), Mock()
        stop.is_set.return_value = lost.is_set.return_value = False
        stop.wait.return_value = False
        event.side_effect = [stop, lost]
        socket = connect.return_value.__enter__.return_value
        socket.ping.return_value.wait.return_value = True
        socket.recv.side_effect = [TimeoutError(), '{"type":"ping"}', ConnectionError(), KeyboardInterrupt()]
        output, errors = io.StringIO(), io.StringIO()
        with self.assertRaises(KeyboardInterrupt):
            call_command("run_neurokeff_odds", stdout=output, stderr=errors)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(reconcile.call_count, 2)
        queue.assert_not_called()
        socket.send.assert_called_once_with('{"type":"pong"}')
        redis.from_url.return_value.lock.return_value.release.assert_called_once()
        self.assertNotIn("do-not-log-me", output.getvalue() + errors.getvalue())

    @patch("game.tasks._fetch_upcoming_for_sport", return_value={"status": "ok"})
    def test_reconcile_uses_existing_sport_sync(self, sync):
        self.assertEqual(reconcile_prematch_odds.run(2), {"status": "ok"})
        sync.assert_called_once_with("football")
        self.assertEqual(reconcile_prematch_odds.run(99)["reason"], "invalid_sport")


@override_settings(**ODDS_SETTINGS)
class PrematchAvailabilitySyncTests(TestCase):
    def setUp(self):
        cache.clear()
        self.sport = Sport.objects.create(external_id=2, code="football", name="Football")
        self.match = Match.objects.create(external_id=501, sport=self.sport, time_status="0",
                                          sync_scope=Match.SyncScope.PREMATCH, score="", live_minute=0,
                                          raw_data={"statistics": "sentinel", "events": "sentinel"})
        self.payload = {"api_id": 501, "odds": {
            "short": {"available": True, "home_win_bet": 1.8, "x_bet": 3.2, "away_win_bet": 4.0},
            "prematch": {"available": True, "updated_at": timezone.now().isoformat(), "bookmakers": [
                {"id": 7, "pk": 7, "name": "BK", "markets": [
                    {"name": "Match Winner", "outcomes": [{"name": "Home", "odds": 9.9}]},
                ]},
            ]},
            "live": {"available": False, "updated_at": None, "bookmakers": []},
        }}
        self.provider = Mock()
        self.provider.fetch_game_odds.side_effect = lambda _: deepcopy(self.payload)
        self.service = MatchSyncService(provider=self.provider)

    def test_updates_only_short_and_comparison_preserving_match_state(self):
        before = Match.objects.values().get(pk=self.match.pk)
        result = self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.assertTrue(result["short_updated"])
        self.assertEqual(Match.objects.values().get(pk=self.match.pk), before)
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 1.8)
        snapshot = self.match.odds_snapshots.get(scope="prematch")
        self.assertEqual(snapshot.bookmakers.get().markets[0]["outcomes"][0]["odds"], 9.9)

    def test_regular_comparison_refresh_does_not_change_short(self):
        MatchOdds.objects.create(match=self.match, home_win_bet=2.5)
        self.service.sync_match_bookmaker_odds(self.match)
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 2.5)

    def test_not_yet_available_short_keeps_saved_line_for_retry(self):
        MatchOdds.objects.create(match=self.match, home_win_bet=2.5)
        self.payload["odds"]["short"] = {"available": False}
        self.assertFalse(self.service.sync_match_bookmaker_odds(self.match, update_short=True)["short_updated"])
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 2.5)

    def test_invalid_response_leaves_short_and_full_line_unchanged(self):
        from game.services.providers.neurokeff import NeurokeffProviderError

        MatchOdds.objects.create(match=self.match, home_win_bet=2.5)
        self.payload["odds"]["short"] = {"available": "true"}
        with self.assertRaises(NeurokeffProviderError):
            self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 2.5)
        self.assertFalse(self.match.odds_snapshots.exists())

    def test_empty_available_short_does_not_erase_existing_coefficients(self):
        from game.services.providers.neurokeff import NeurokeffProviderError

        MatchOdds.objects.create(match=self.match, home_win_bet=2.5)
        self.payload["odds"]["short"] = {"available": True, "home_win_bet": None, "totals_all": {}}
        with self.assertRaises(NeurokeffProviderError):
            self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 2.5)

    def test_updated_event_refreshes_prices_and_bookmaker_composition(self):
        from game.services.bet_options import build_match_coupon_options

        self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.payload["odds"]["short"]["home_win_bet"] = 2.3
        book = self.payload["odds"]["prematch"]["bookmakers"][0]
        book.update(pk=8, id=8, name="New BK")
        result = self.service.sync_match_bookmaker_odds(self.match, update_short=True, allow_empty_short=True)
        self.assertTrue(result["short_updated"])
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 2.3)
        self.assertEqual(self.match.odds_snapshots.get(scope="prematch").bookmakers.get().name, "New BK")
        self.match.refresh_from_db()
        options = build_match_coupon_options(self.match)
        self.assertEqual(options["items"][0]["coefficient"], "2.30")

    def test_updated_event_applies_suspended_outcome_and_removed_shortcut(self):
        from game.services.bet_options import match_bet_options

        self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.payload["odds"]["short"]["home_win_bet"] = None
        self.payload["odds"]["prematch"]["bookmakers"][0]["markets"][0]["outcomes"][0]["suspended"] = True
        self.service.sync_match_bookmaker_odds(self.match, update_short=True, allow_empty_short=True)
        stored = self.match.odds_snapshots.get(scope="prematch").bookmakers.get().markets[0]["outcomes"][0]
        self.assertTrue(stored["suspended"])
        self.match.refresh_from_db()
        options = match_bet_options(self.match).values()
        self.assertFalse(any(option.market == "winner" and option.outcome_code == "1" for option in options))

    def test_updated_event_clears_available_but_empty_short_line(self):
        self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.payload["odds"]["short"] = {"available": True, "home_win_bet": None, "totals_all": {}}
        self.assertTrue(self.service.sync_match_bookmaker_odds(
            self.match, update_short=True, allow_empty_short=True,
        )["short_updated"])
        self.assertIsNone(MatchOdds.objects.get(match=self.match).home_win_bet)

    def test_updated_event_clears_unavailable_short_even_if_old_prices_are_present(self):
        from game.services.bet_options import match_bet_options

        self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.payload["odds"]["short"]["available"] = False
        result = self.service.sync_match_bookmaker_odds(self.match, update_short=True, allow_empty_short=True)
        self.assertTrue(result["short_updated"])
        self.assertIsNone(MatchOdds.objects.get(match=self.match).home_win_bet)
        self.match.refresh_from_db()
        self.assertFalse(match_bet_options(self.match))

    def test_updated_event_clears_removed_line_with_no_provider_timestamp(self):
        self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.payload["odds"]["prematch"].update(available=False, updated_at=None, bookmakers=[])
        self.payload["odds"]["short"] = {"available": False}
        result = self.service.sync_match_bookmaker_odds(self.match, update_short=True, allow_empty_short=True)
        self.assertTrue(result["short_updated"])
        self.assertFalse(self.match.odds_snapshots.get(scope="prematch").available)
        self.assertIsNone(MatchOdds.objects.get(match=self.match).home_win_bet)

    def test_old_polling_cannot_restore_line_after_ws_triggered_withdrawal(self):
        started = timezone.now() - timedelta(seconds=1)
        self.payload["odds"]["short"] = {"available": False}
        self.service.sync_match_bookmaker_odds(self.match, update_short=True, allow_empty_short=True)
        self.service._sync_odds(self.match, {"home_win_bet": 7.0}, observed_at=started)
        self.assertIsNone(MatchOdds.objects.get(match=self.match).home_win_bet)
        self.service._sync_odds(self.match, {"home_win_bet": 2.1}, observed_at=timezone.now())
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 2.1)

    def test_normal_polling_honours_explicit_short_unavailability(self):
        MatchOdds.objects.create(match=self.match, home_win_bet=2.5)
        self.service._sync_odds(self.match, {"available": False, "home_win_bet": 9.9})
        self.assertIsNone(MatchOdds.objects.get(match=self.match).home_win_bet)

    def test_older_polling_cannot_overwrite_a_newer_polling_response(self):
        started = timezone.now() - timedelta(seconds=1)
        self.service._sync_odds(self.match, {"home_win_bet": 2.1})
        self.service._sync_odds(self.match, {"home_win_bet": 7.0}, observed_at=started)
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 2.1)

    def test_transition_to_live_during_rest_cannot_restore_prematch_short(self):
        MatchOdds.objects.create(match=self.match, home_win_bet=2.5)

        def response(_):
            Match.objects.filter(pk=self.match.pk).update(sync_scope=Match.SyncScope.LIVE, score="1-0")
            return deepcopy(self.payload)

        self.provider.fetch_game_odds.side_effect = response
        result = self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.assertFalse(result["short_updated"])
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 2.5)
        self.match.refresh_from_db()
        self.assertEqual(self.match.score, "1-0")

    def test_older_provider_line_cannot_replace_short(self):
        self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.payload["odds"]["prematch"]["updated_at"] = (timezone.now() - timedelta(days=1)).isoformat()
        self.payload["odds"]["short"]["home_win_bet"] = 7.0
        result = self.service.sync_match_bookmaker_odds(self.match, update_short=True)
        self.assertFalse(result["short_updated"])
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 1.8)

    def test_newer_normal_rest_sync_wins_over_in_flight_request(self):
        MatchOdds.objects.create(match=self.match, home_win_bet=2.5)

        def response(_):
            Match.objects.filter(pk=self.match.pk).update(last_seen_at=timezone.now())
            return deepcopy(self.payload)

        self.provider.fetch_game_odds.side_effect = response
        self.assertFalse(self.service.sync_match_bookmaker_odds(self.match, update_short=True)["short_updated"])
        self.assertEqual(MatchOdds.objects.get(match=self.match).home_win_bet, 2.5)

    @patch("game.tasks.MatchSyncService")
    def test_task_updates_existing_match_odds_without_state_sync(self, factory):
        factory.return_value.sync_match_bookmaker_odds.return_value = {"status": "ok", "short_updated": True}
        result = refresh_prematch_match_odds.run(501, 2)
        self.assertTrue(result["short_updated"])
        factory.return_value.sync_match_states.assert_not_called()
        self.assertTrue(factory.return_value.sync_match_bookmaker_odds.call_args.kwargs["update_short"])
        self.assertFalse(factory.return_value.sync_match_bookmaker_odds.call_args.kwargs["allow_empty_short"])

    @patch("game.tasks.MatchSyncService")
    def test_updated_task_allows_authoritative_line_withdrawal(self, factory):
        factory.return_value.sync_match_bookmaker_odds.return_value = {"status": "ok", "short_updated": True}
        refresh_prematch_match_odds.run(501, 2, "prematch.odds.updated")
        self.assertTrue(factory.return_value.sync_match_bookmaker_odds.call_args.kwargs["allow_empty_short"])
        factory.return_value.sync_match_states.assert_not_called()

    @patch("game.tasks.MatchSyncService")
    def test_busy_shared_lock_retries_updated_event_instead_of_dropping_it(self, factory):
        cache.set(f"match-full-odds:{self.match.pk}", 1, timeout=60)
        with patch.object(refresh_prematch_match_odds, "retry", side_effect=RuntimeError("retry queued")) as retry:
            with self.assertRaisesMessage(RuntimeError, "retry queued"):
                refresh_prematch_match_odds.run(501, 2, "prematch.odds.updated")
        retry.assert_called_once_with(countdown=5, max_retries=12)
        factory.return_value.sync_match_bookmaker_odds.assert_not_called()

    @patch("game.tasks.MatchSyncService")
    def test_late_event_for_live_match_does_not_fetch_or_overwrite(self, factory):
        Match.objects.filter(pk=self.match.pk).update(sync_scope=Match.SyncScope.LIVE)
        self.assertEqual(refresh_prematch_match_odds.run(501, 2)["reason"], "not_prematch")
        factory.return_value.sync_match_bookmaker_odds.assert_not_called()

    @patch("game.tasks.MatchSyncService")
    def test_event_with_wrong_sport_does_not_fetch_odds(self, factory):
        self.assertEqual(refresh_prematch_match_odds.run(501, 3)["reason"], "sport_mismatch")
        factory.return_value.sync_match_bookmaker_odds.assert_not_called()

    @patch("game.tasks.MatchSyncService")
    def test_unknown_match_discovery_is_followed_by_odds_fetch(self, factory):
        def discover(_):
            Match.objects.create(external_id=999, sport=self.sport, sync_scope=Match.SyncScope.PREMATCH)

        factory.return_value.sync_match_states.side_effect = discover
        factory.return_value.sync_match_bookmaker_odds.return_value = {"status": "ok", "short_updated": True}
        refresh_prematch_match_odds.run(999, 2)
        factory.return_value.sync_match_states.assert_called_once_with([999])
        self.assertTrue(factory.return_value.sync_match_bookmaker_odds.called)


@override_settings(**ODDS_SETTINGS, NEUROKEFF_PREMATCH_FULL_ODDS_BATCH_SIZE=100,
                   NEUROKEFF_PREMATCH_FULL_ODDS_REFRESH_SECONDS=900, NEUROKEFF_FINISHED_DAYS_BACK=2)
class PrematchOddsRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.sport = Sport.objects.create(external_id=2, code="football", name="Football")
        self.now = timezone.now()

    def match(self, game_id, *, phase="prematch", starts_at=None):
        return Match.objects.create(external_id=game_id, sport=self.sport, sync_scope=phase,
            starts_at=starts_at or self.now + timedelta(hours=2))

    def snapshot(self, match, *, minutes_ago=0, has_line=True):
        stamp = self.now - timedelta(minutes=minutes_ago)
        snapshot = MatchOddsSnapshot.objects.create(match=match, scope="prematch", available=has_line,
            requested_at=stamp, fetched_at=stamp, provider_updated_at=stamp)
        if has_line:
            MatchBookmakerOdds.objects.create(snapshot=snapshot, bookmaker_key="7", name="BK", markets=[])
        return snapshot

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    def test_recovers_missing_and_stale_lines_but_not_fresh_or_existing_archives(self, queue):
        missing = self.match(501)
        stale = self.match(502)
        self.snapshot(stale, minutes_ago=16)
        self.snapshot(self.match(503))
        self.snapshot(self.match(504, phase="live", starts_at=self.now - timedelta(hours=1)), minutes_ago=60)
        live = self.match(505, phase="live", starts_at=self.now - timedelta(hours=1))
        finished = self.match(506, phase="finished", starts_at=self.now - timedelta(hours=3))
        self.match(507, phase="finished", starts_at=self.now - timedelta(days=3))
        needs_final_check = self.match(509, phase="live", starts_at=self.now - timedelta(hours=1))
        self.snapshot(needs_final_check, minutes_ago=90)
        hockey = Sport.objects.create(external_id=3, code="hockey", name="Hockey")
        Match.objects.create(external_id=508, sport=hockey, sync_scope="prematch", starts_at=self.now + timedelta(hours=1))
        with self.assertNumQueries(1):
            self.assertEqual(queue_missing_prematch_odds("football"), 5)
        self.assertEqual({call.kwargs["args"][0] for call in queue.call_args_list},
                         {missing.pk, stale.pk, live.pk, finished.pk, needs_final_check.pk})
        self.assertEqual(queue_missing_prematch_odds("football"), 0)

    @override_settings(NEUROKEFF_PREMATCH_FULL_ODDS_BATCH_SIZE=2)
    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    def test_bounded_batches_advance_past_unavailable_games(self, queue):
        matches = [self.match(501 + i) for i in range(5)]
        self.assertEqual(queue_missing_prematch_odds(), 2)
        self.assertEqual([call.kwargs["args"][0] for call in queue.call_args_list], [m.pk for m in matches[:2]])
        for match in matches[:2]:
            self.snapshot(match, has_line=False)
        queue.reset_mock()
        self.assertEqual(queue_missing_prematch_odds(), 2)
        self.assertEqual([call.kwargs["args"][0] for call in queue.call_args_list], [m.pk for m in matches[2:4]])

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    @patch("game.tasks.MatchSyncService")
    def test_both_periodic_polling_and_reconnect_queue_full_rest_recovery(self, factory, queue):
        match = self.match(501)
        factory.return_value.sync_upcoming.return_value = {"status": "ok"}
        for run in (lambda: _fetch_upcoming_for_sport("football"), lambda: reconcile_prematch_odds.run(2)):
            cache.clear()
            result = run()
            self.assertEqual(result["full_odds_queued"], 1)
        self.assertEqual(queue.call_count, 2)
        queue.assert_called_with(args=[match.pk], retry=False)
        factory.return_value.sync_match_bookmaker_odds.assert_not_called()

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    @patch("game.tasks.MatchSyncService")
    def test_failed_list_sync_does_not_launch_another_batch(self, factory, queue):
        from game.services.providers.neurokeff import NeurokeffProviderError

        self.match(501)
        factory.return_value.sync_upcoming.side_effect = NeurokeffProviderError("provider unavailable")
        self.assertEqual(_fetch_upcoming_for_sport("football")["status"], "error")
        queue.assert_not_called()

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async", side_effect=RuntimeError("broker unavailable"))
    def test_failed_full_line_enqueue_releases_shared_queue_gate(self, queue):
        match = self.match(501)
        with self.assertRaises(RuntimeError):
            queue_match_odds_refresh(match.pk)
        self.assertIsNone(cache.get(f"match-odds-comparison-queue:{match.pk}"))
        queue.side_effect = None
        self.assertTrue(queue_match_odds_refresh(match.pk))
        self.assertFalse(queue_match_odds_refresh(match.pk))
