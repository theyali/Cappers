from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from game.models import Match
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
                    "time_status": "8",
                    "score": "0:0",
                }
            ]
        )

        result = MatchSyncService(provider=provider).sync_live()

        match = Match.objects.get(external_id=910003)
        self.assertEqual(match.sync_scope, Match.SyncScope.FINISHED)
        self.assertEqual(result["scopes"], {Match.SyncScope.FINISHED: 1})

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
            "2": Match.SyncScope.LIVE,
            "3": Match.SyncScope.FINISHED,
            "4": Match.SyncScope.FINISHED,
            "5": Match.SyncScope.FINISHED,
            "6": Match.SyncScope.FINISHED,
            "7": Match.SyncScope.FINISHED,
            "8": Match.SyncScope.FINISHED,
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
