from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from game.models import Match, MatchEvent, Provider, Sport, Team
from game.services.match_sync import MatchSyncService
from game.services.providers.neurokeff import NeurokeffProviderError
from game.tasks import refresh_match_events


class MutableEventsProvider:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {"events": {"available": True, "items": []}}
        self.error = error
        self.requested_external_ids = []

    def fetch_game_events(self, external_id):
        self.requested_external_ids.append(external_id)
        if self.error is not None:
            raise self.error
        return self.payload


class SelectiveEventsProvider:
    def __init__(self, *, failing_external_id, payload):
        self.failing_external_id = failing_external_id
        self.payload = payload
        self.requested_external_ids = []

    def fetch_game_events(self, external_id):
        self.requested_external_ids.append(external_id)
        if external_id == self.failing_external_id:
            raise NeurokeffProviderError("single match failed")
        return self.payload


def event_payload(
    event_id,
    *,
    minute=12,
    seq=1,
    event_type="goal",
    player_id=7001,
    player_name="Player",
    team=None,
    participants=None,
):
    item = {
        "id": event_id,
        "seq": seq,
        "type": {"code": event_type, "name": event_type},
        "time": {"minute": minute},
        "player": {"id": player_id, "name": player_name},
    }
    if team is not None:
        item["team"] = team
    if participants is not None:
        item["participants"] = participants
    return item


class MatchEventLifecycleTests(TestCase):
    def setUp(self):
        self.match = Match.objects.create(
            external_id=920001,
            sync_scope=Match.SyncScope.LIVE,
        )
        self.provider = MutableEventsProvider()
        self.service = MatchSyncService(provider=self.provider)

    def sync_items(self, items):
        self.provider.payload = {
            "events": {
                "available": True,
                "items": items,
            }
        }
        return self.service.sync_match_events(self.match)

    def test_repeated_sync_updates_event_and_replaces_participants_without_duplicates(self):
        first_participants = [
            {
                "role": "scorer",
                "player": {"id": 7001, "name": "First Player"},
            },
            {
                "role": "assist",
                "player": {"id": 7002, "name": "First Assist"},
            },
        ]
        self.sync_items(
            [
                event_payload(
                    200001,
                    minute=11,
                    player_name="First Player",
                    participants=first_participants,
                )
            ]
        )
        original = MatchEvent.objects.get(match=self.match)
        original_pk = original.pk
        self.assertEqual(original.participants_rows.count(), 2)

        second_participants = [
            {
                "role": "scorer",
                "player": {"id": 7003, "name": "Corrected Player"},
            }
        ]
        result = self.sync_items(
            [
                event_payload(
                    200001,
                    minute=13,
                    player_id=7003,
                    player_name="Corrected Player",
                    participants=second_participants,
                )
            ]
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["rows"], 1)
        self.assertEqual(MatchEvent.objects.filter(match=self.match).count(), 1)
        updated = MatchEvent.objects.get(match=self.match)
        self.assertEqual(updated.pk, original_pk)
        self.assertEqual(updated.minute, 13)
        self.assertEqual(updated.player_external_id, 7003)
        self.assertEqual(updated.player_name, "Corrected Player")
        participant = updated.participants_rows.get()
        self.assertEqual(participant.role, "scorer")
        self.assertEqual(participant.player_external_id, 7003)
        self.assertEqual(self.provider.requested_external_ids, [self.match.external_id] * 2)

    def test_authoritative_snapshot_removes_only_stale_events(self):
        active = event_payload(200002, minute=20, player_name="Active")
        stale = event_payload(200003, minute=25, player_name="Stale")
        self.sync_items([active, stale])

        active["time"]["minute"] = 21
        result = self.sync_items([active])

        self.assertEqual(result["deleted"], 1)
        self.assertFalse(MatchEvent.objects.filter(match=self.match, external_id=200003).exists())
        remaining = MatchEvent.objects.get(match=self.match)
        self.assertEqual(remaining.external_id, 200002)
        self.assertEqual(remaining.minute, 21)

    def test_team_is_linked_by_external_id_before_side_fallback(self):
        sport = Sport.objects.create(
            external_id=31,
            code="event-test-football",
            name="Football",
        )
        home = Team.objects.create(
            external_id=5101,
            sport=sport,
            name="Home",
        )
        away = Team.objects.create(
            external_id=5102,
            sport=sport,
            name="Away",
        )
        self.match.sport = sport
        self.match.home_team = home
        self.match.away_team = away
        self.match.save(update_fields=("sport", "home_team", "away_team", "updated_at"))

        self.sync_items(
            [
                event_payload(
                    200004,
                    team={"id": away.external_id, "side": "home", "name": "Away"},
                ),
                event_payload(
                    200005,
                    minute=30,
                    team={"side": "home", "name": "Home"},
                ),
            ]
        )

        by_id = MatchEvent.objects.get(external_id=200004)
        by_side = MatchEvent.objects.get(external_id=200005)
        self.assertEqual(by_id.team, away)
        self.assertEqual(by_side.team, home)

    def test_event_key_prefers_external_id_then_uid_then_sequence(self):
        items = [
            {
                "id": 200006,
                "uid": 300006,
                "seq": 6,
                "type": {"code": "goal"},
            },
            {
                "uid": 300007,
                "seq": 7,
                "type": {"code": "yellow_card"},
            },
            {
                "seq": 8,
                "type": {"code": "substitution"},
            },
        ]

        self.sync_items(items)

        self.assertSetEqual(
            set(MatchEvent.objects.filter(match=self.match).values_list("event_key", flat=True)),
            {"id:200006", "uid:300007", "seq:8"},
        )

    def test_default_model_order_is_chronological_then_sequence(self):
        MatchEvent.objects.create(match=self.match, event_key="late", minute=80, seq=1)
        MatchEvent.objects.create(match=self.match, event_key="second", minute=10, seq=2)
        MatchEvent.objects.create(match=self.match, event_key="first", minute=10, seq=1)

        keys = list(
            MatchEvent.objects.filter(match=self.match).values_list("event_key", flat=True)
        )

        self.assertEqual(keys, ["first", "second", "late"])

    def test_prematch_is_skipped_without_provider_request(self):
        self.match.sync_scope = Match.SyncScope.PREMATCH
        self.match.save(update_fields=("sync_scope", "updated_at"))

        result = self.service.sync_match_events(self.match)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "prematch")
        self.assertIsNone(result["available"])
        self.assertEqual(result["rows"], 0)
        self.assertEqual(self.provider.requested_external_ids, [])

    def test_provider_error_propagates_without_changing_known_state(self):
        original_fetched_at = timezone.now()
        self.match.events_fetched_at = original_fetched_at
        self.match.events_available = True
        self.match.save(
            update_fields=("events_fetched_at", "events_available", "updated_at")
        )
        MatchEvent.objects.create(
            match=self.match,
            event_key="id:200007",
            external_id=200007,
            event_type_code="goal",
        )
        self.provider.error = NeurokeffProviderError("provider unavailable")

        with self.assertRaisesMessage(NeurokeffProviderError, "provider unavailable"):
            self.service.sync_match_events(self.match)

        self.match.refresh_from_db()
        self.assertEqual(self.match.events_fetched_at, original_fetched_at)
        self.assertTrue(self.match.events_available)
        self.assertTrue(MatchEvent.objects.filter(match=self.match, external_id=200007).exists())

    def test_sync_is_atomic_when_participant_write_fails(self):
        payload = event_payload(
            200008,
            participants=[
                {
                    "role": "scorer",
                    "player": {"id": 7008, "name": "Player"},
                }
            ],
        )

        with patch(
            "game.services.match_sync.MatchEventParticipant.objects.bulk_create",
            side_effect=IntegrityError("participant write failed"),
        ):
            with self.assertRaisesMessage(IntegrityError, "participant write failed"):
                self.sync_items([payload])

        self.match.refresh_from_db()
        self.assertFalse(MatchEvent.objects.filter(match=self.match).exists())
        self.assertIsNone(self.match.events_fetched_at)
        self.assertIsNone(self.match.events_available)
        self.assertNotIn("events", self.match.raw_data)

    def test_nonempty_list_with_only_invalid_items_preserves_known_events(self):
        MatchEvent.objects.create(
            match=self.match,
            event_key="id:200010",
            external_id=200010,
            event_type_code="goal",
        )
        self.provider.payload = {
            "events": {
                "available": True,
                "items": [None, "invalid"],
            }
        }

        result = self.service.sync_match_events(self.match)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "invalid_items")
        self.assertTrue(MatchEvent.objects.filter(match=self.match, external_id=200010).exists())
        self.match.refresh_from_db()
        self.assertIsNone(self.match.events_available)

    def test_live_batch_continues_after_one_match_provider_error(self):
        successful_match = Match.objects.create(
            external_id=920003,
            sync_scope=Match.SyncScope.LIVE,
        )
        provider = SelectiveEventsProvider(
            failing_external_id=self.match.external_id,
            payload={
                "events": {
                    "available": True,
                    "items": [event_payload(200011, minute=55)],
                }
            },
        )

        with self.assertLogs("game.services.match_sync", level="ERROR") as logs:
            result = MatchSyncService(provider=provider).sync_live_events(limit=2)

        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["errors"], 1)
        self.assertIn("Failed to sync Neurokeff events", logs.output[0])
        self.assertEqual(
            provider.requested_external_ids,
            [self.match.external_id, successful_match.external_id],
        )
        self.assertFalse(MatchEvent.objects.filter(match=self.match).exists())
        self.assertTrue(
            MatchEvent.objects.filter(match=successful_match, external_id=200011).exists()
        )

    def test_embedded_nested_events_use_same_persistence_path(self):
        result = self.service._sync_embedded_events(
            self.match,
            {
                "data": {
                    "events": {
                        "available": True,
                        "items": [event_payload(200009, minute=42)],
                    }
                }
            },
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(MatchEvent.objects.filter(match=self.match, external_id=200009).exists())
        self.assertEqual(self.provider.requested_external_ids, [])


class MatchEventTaskTests(TestCase):
    def test_refresh_task_returns_match_not_found(self):
        result = refresh_match_events.run(999999999)

        self.assertEqual(
            result,
            {
                "status": "skipped",
                "reason": "match_not_found",
                "match_id": 999999999,
            },
        )

    def test_refresh_task_converts_provider_error_to_structured_result(self):
        match = Match.objects.create(
            external_id=920002,
            sync_scope=Match.SyncScope.LIVE,
        )
        with patch("game.tasks.MatchSyncService") as service_class:
            service_class.return_value.sync_match_events.side_effect = NeurokeffProviderError(
                "events endpoint timeout"
            )

            result = refresh_match_events.run(match.pk)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "provider_error")
        self.assertEqual(result["match_id"], match.pk)
        self.assertEqual(result["message"], "events endpoint timeout")
        service_class.return_value.sync_match_events.assert_called_once()
