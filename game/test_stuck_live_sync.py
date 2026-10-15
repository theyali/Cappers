from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from game.match_detail_views import _match_events_are_stale
from game.models import Match, MatchEvent
from game.services.match_sync import MatchSyncService


class FakeInfoProvider:
    def __init__(self, payloads):
        self.payloads = payloads
        self.requested_ids = []

    def fetch_matches_info(self, ids):
        self.requested_ids.extend(ids)
        return self.payloads


class FakeLiveProvider:
    def __init__(self, payloads):
        self.payloads = payloads

    def fetch_live_matches(self):
        return self.payloads


class FakePredictionProvider:
    def __init__(self, payload):
        self.payload = payload
        self.requested_external_ids = []

    def fetch_game_predictions(self, external_id):
        self.requested_external_ids.append(external_id)
        return self.payload


class FakeEventsProvider:
    def __init__(self, payload):
        self.payload = payload
        self.requested_external_ids = []

    def fetch_game_events(self, external_id):
        self.requested_external_ids.append(external_id)
        return self.payload


class StuckLiveSyncTests(TestCase):
    @override_settings(NEUROKEFF_STUCK_LIVE_AFTER_MINUTES=10)
    def test_stuck_live_match_is_updated_from_game_info_payload(self):
        stale_live = Match.objects.create(
            external_id=910001,
            sync_scope=Match.SyncScope.LIVE,
            score="1:0",
            last_seen_at=timezone.now() - timedelta(minutes=30),
        )
        fresh_live = Match.objects.create(
            external_id=910002,
            sync_scope=Match.SyncScope.LIVE,
            last_seen_at=timezone.now(),
        )
        provider = FakeInfoProvider(
            [
                {
                    "id": stale_live.external_id,
                    "status": "finished",
                    "time_status": "FT",
                    "score": "2:1",
                }
            ]
        )

        result = MatchSyncService(provider=provider).sync_stuck_live_matches()

        stale_live.refresh_from_db()
        fresh_live.refresh_from_db()
        self.assertEqual(provider.requested_ids, [stale_live.external_id])
        self.assertEqual(stale_live.sync_scope, Match.SyncScope.FINISHED)
        self.assertEqual(stale_live.score, "2:1")
        self.assertEqual(fresh_live.sync_scope, Match.SyncScope.LIVE)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["scopes"], {Match.SyncScope.FINISHED: 1})

    def test_live_sync_uses_payload_status_instead_of_forcing_live(self):
        provider = FakeLiveProvider(
            [
                {
                    "id": 910003,
                    "time_status": "4",
                    "score": "0:0",
                }
            ]
        )

        result = MatchSyncService(provider=provider).sync_live()

        match = Match.objects.get(external_id=910003)
        self.assertEqual(match.sync_scope, Match.SyncScope.POSTPONED)
        self.assertEqual(result["scopes"], {Match.SyncScope.POSTPONED: 1})

    def test_scope_can_be_read_from_nested_status_payload(self):
        scope = MatchSyncService._scope_from_payload(
            {"status": {"short": "FT", "long": "Match Finished"}},
            default=Match.SyncScope.LIVE,
        )

        self.assertEqual(scope, Match.SyncScope.FINISHED)

    def test_neurokeff_finished_numeric_status_is_finished(self):
        scope = MatchSyncService._scope_from_payload(
            {"time_status": "3"},
            default=Match.SyncScope.LIVE,
        )

        self.assertEqual(scope, Match.SyncScope.FINISHED)

    def test_neurokeff_numeric_statuses_are_mapped_to_local_scopes(self):
        expected = {
            "0": Match.SyncScope.PREMATCH,
            "1": Match.SyncScope.LIVE,
            "2": Match.SyncScope.CONNECTION_LOST,
            "3": Match.SyncScope.FINISHED,
            "4": Match.SyncScope.POSTPONED,
            "5": Match.SyncScope.CANCELED,
            "6": Match.SyncScope.FORFEIT,
            "7": Match.SyncScope.INTERRUPTED,
            "8": Match.SyncScope.ABANDONED,
        }

        for status, scope in expected.items():
            with self.subTest(status=status):
                self.assertEqual(
                    MatchSyncService._scope_from_payload(
                        {"time_status": status},
                        default=Match.SyncScope.LIVE,
                    ),
                    scope,
                )

    def test_match_predictions_are_saved_by_external_id(self):
        match = Match.objects.create(
            external_id=910004,
            sync_scope=Match.SyncScope.FINISHED,
        )
        payload = {
            "api_id": match.external_id,
            "predictions": {
                "available": True,
                "snapshot": {"percent": {"home": 10, "draw": 45, "away": 45}},
            },
        }
        provider = FakePredictionProvider(payload)

        result = MatchSyncService(provider=provider).sync_match_predictions(match)

        match.refresh_from_db()
        self.assertEqual(provider.requested_external_ids, [match.external_id])
        self.assertEqual(match.provider_predictions, payload)
        self.assertIsNotNone(match.provider_predictions_updated_at)

    def test_match_events_are_saved_by_external_id(self):
        match = Match.objects.create(
            external_id=910005,
            sync_scope=Match.SyncScope.FINISHED,
        )
        payload = {
            "api_id": match.external_id,
            "events": {
                "available": True,
                "items": [
                    {
                        "id": 1906533,
                        "uid": 195341273,
                        "seq": 3,
                        "type": {"code": "goal", "name": "goal", "name_ru": "гол"},
                        "detail": {"code": "regular", "name": "regular", "name_ru": "с игры"},
                        "time": {"minute": 12, "extra": None},
                        "team": {"id": 5001, "name": "Home", "name_ru": "Хозяева", "side": "home"},
                        "player": {"id": 7001, "name": "John Smith", "name_ru": "Джон Смит"},
                        "assist": {"id": 7002, "name": "Alex Lane", "name_ru": "Алекс Лейн"},
                        "participants": [
                            {
                                "role": "scorer",
                                "player": {"id": 7001, "name": "John Smith", "name_ru": "Джон Смит"},
                            }
                        ],
                    }
                ],
            },
        }
        provider = FakeEventsProvider(payload)

        result = MatchSyncService(provider=provider).sync_match_events(match)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(provider.requested_external_ids, [match.external_id])
        event = MatchEvent.objects.get(match=match)
        self.assertEqual(event.event_key, "id:1906533")
        self.assertEqual(event.event_type_code, "goal")
        self.assertEqual(event.event_type_name_ru, "гол")
        self.assertEqual(event.minute, 12)
        self.assertEqual(event.player_name_ru, "Джон Смит")
        self.assertEqual(event.participants_rows.count(), 1)

        provider.payload = {"events": {"available": True, "items": []}}
        result = MatchSyncService(provider=provider).sync_match_events(match)

        self.assertEqual(result["reason"], "empty")
        self.assertEqual(result["status"], "ok")
        self.assertFalse(MatchEvent.objects.filter(match=match).exists())
        self.assertTrue(result["available"])

        match.refresh_from_db()
        self.assertTrue(match.events_available)
        self.assertIsNotNone(match.events_fetched_at)

    def test_match_events_refresh_uses_provider_instead_of_stored_snapshot(self):
        stale_event = {
            "id": 1906534,
            "type": {"code": "goal"},
            "time": {"minute": 12},
            "player": {"id": 7001, "name": "Old Player"},
        }
        fresh_event = {
            "id": 1906535,
            "type": {"code": "goal"},
            "time": {"minute": 34},
            "player": {"id": 7002, "name": "Fresh Player"},
        }
        match = Match.objects.create(
            external_id=910006,
            sync_scope=Match.SyncScope.LIVE,
            raw_data={"events": {"available": True, "items": [stale_event]}},
        )
        provider = FakeEventsProvider(
            {"events": {"available": True, "items": [fresh_event]}}
        )

        result = MatchSyncService(provider=provider).sync_match_events(match)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(provider.requested_external_ids, [match.external_id])
        self.assertFalse(MatchEvent.objects.filter(match=match, external_id=1906534).exists())
        event = MatchEvent.objects.get(match=match)
        self.assertEqual(event.external_id, 1906535)
        self.assertEqual(event.minute, 34)
        self.assertEqual(event.player_name, "Fresh Player")

    def test_unavailable_events_preserve_known_rows_and_record_attempt(self):
        match = Match.objects.create(
            external_id=910007,
            sync_scope=Match.SyncScope.FINISHED,
        )
        MatchEvent.objects.create(
            match=match,
            event_key="id:1906536",
            external_id=1906536,
            event_type_code="goal",
        )
        provider = FakeEventsProvider(
            {"events": {"available": False, "items": []}}
        )

        result = MatchSyncService(provider=provider).sync_match_events(match)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "unavailable")
        self.assertFalse(result["available"])
        self.assertTrue(MatchEvent.objects.filter(match=match, external_id=1906536).exists())
        match.refresh_from_db()
        self.assertFalse(match.events_available)
        self.assertIsNotNone(match.events_fetched_at)

    def test_event_sync_preserves_concurrently_updated_match_raw_data(self):
        match = Match.objects.create(
            external_id=910013,
            sync_scope=Match.SyncScope.LIVE,
            raw_data={"score": "0:0"},
        )
        Match.objects.filter(pk=match.pk).update(
            raw_data={"score": "1:0", "fresh_status": "live"},
        )
        provider = FakeEventsProvider(
            {"events": {"available": False, "items": []}}
        )

        MatchSyncService(provider=provider).sync_match_events(match)

        match.refresh_from_db()
        self.assertEqual(match.raw_data["score"], "1:0")
        self.assertEqual(match.raw_data["fresh_status"], "live")
        self.assertEqual(match.raw_data["events"]["available"], False)

    def test_invalid_event_items_preserve_known_rows(self):
        match = Match.objects.create(
            external_id=910008,
            sync_scope=Match.SyncScope.LIVE,
        )
        MatchEvent.objects.create(
            match=match,
            event_key="id:1906537",
            external_id=1906537,
            event_type_code="goal",
        )
        provider = FakeEventsProvider(
            {"events": {"available": True, "items": {"id": 1906538}}}
        )

        result = MatchSyncService(provider=provider).sync_match_events(match)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "invalid_items")
        self.assertTrue(result["available"])
        self.assertTrue(MatchEvent.objects.filter(match=match, external_id=1906537).exists())
        match.refresh_from_db()
        self.assertIsNone(match.events_available)

    def test_live_events_prioritize_matches_that_were_never_fetched(self):
        fetched_match = Match.objects.create(
            external_id=910010,
            sync_scope=Match.SyncScope.LIVE,
            events_fetched_at=timezone.now(),
            events_available=False,
        )
        pending_match = Match.objects.create(
            external_id=910011,
            sync_scope=Match.SyncScope.LIVE,
        )
        provider = FakeEventsProvider(
            {"events": {"available": False, "items": []}}
        )

        result = MatchSyncService(provider=provider).sync_live_events(limit=1)

        self.assertEqual(result["checked"], 1)
        self.assertEqual(provider.requested_external_ids, [pending_match.external_id])
        fetched_match.refresh_from_db()
        self.assertFalse(fetched_match.events_available)

    def test_string_false_availability_does_not_clear_known_events(self):
        match = Match.objects.create(
            external_id=910012,
            sync_scope=Match.SyncScope.FINISHED,
        )
        MatchEvent.objects.create(
            match=match,
            event_key="id:1906539",
            external_id=1906539,
            event_type_code="goal",
        )
        provider = FakeEventsProvider(
            {"events": {"available": "false", "items": []}}
        )

        result = MatchSyncService(provider=provider).sync_match_events(match)

        self.assertEqual(result["reason"], "unavailable")
        self.assertFalse(result["available"])
        self.assertTrue(MatchEvent.objects.filter(match=match, external_id=1906539).exists())

    @override_settings(NEUROKEFF_FINISHED_EVENTS_RETRY_SECONDS=3600)
    def test_finished_unavailable_events_respect_retry_window(self):
        match = Match.objects.create(
            external_id=910014,
            sync_scope=Match.SyncScope.FINISHED,
            events_fetched_at=timezone.now(),
            events_available=False,
        )

        self.assertFalse(_match_events_are_stale(match))

        match.events_fetched_at = timezone.now() - timedelta(hours=2)
        self.assertTrue(_match_events_are_stale(match))

    def test_finished_available_events_do_not_refresh_again(self):
        match = Match.objects.create(
            external_id=910015,
            sync_scope=Match.SyncScope.FINISHED,
            events_fetched_at=timezone.now() - timedelta(days=1),
            events_available=True,
        )

        self.assertFalse(_match_events_are_stale(match))

    def test_fallback_event_key_is_stable_when_item_position_changes(self):
        event = {
            "type": {"code": "yellow_card"},
            "detail": {"code": "unsporting_behaviour"},
            "time": {"minute": 44},
            "team": {"id": 5001, "side": "home"},
            "player": {"id": 7003, "name": "Carded Player"},
        }
        match = Match.objects.create(
            external_id=910009,
            sync_scope=Match.SyncScope.LIVE,
        )
        provider = FakeEventsProvider(
            {"events": {"available": True, "items": [event]}}
        )
        service = MatchSyncService(provider=provider)

        service.sync_match_events(match)
        first_key = MatchEvent.objects.get(match=match).event_key
        provider.payload = {
            "events": {
                "available": True,
                "items": [
                    {
                        "type": {"code": "goal"},
                        "time": {"minute": 12},
                        "team": {"id": 5002, "side": "away"},
                        "player": {"id": 7004, "name": "Scorer"},
                    },
                    event,
                ],
            }
        }

        service.sync_match_events(match)

        self.assertTrue(MatchEvent.objects.filter(match=match, event_key=first_key).exists())
        self.assertEqual(MatchEvent.objects.filter(match=match).count(), 2)
