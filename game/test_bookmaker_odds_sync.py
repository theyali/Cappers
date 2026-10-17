from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase

from game.models import ComparisonBookmaker, Match, MatchOdds, MatchOddsSnapshot, MatchBookmakerOdds
from game.services.match_sync import MatchSyncService
from game.services.providers.neurokeff import NeurokeffProviderError, NeurokeffSportsProvider
from game.tasks import refresh_match_bookmaker_odds


def bookmaker(pk=1, price=1.91):
    return {"id": pk, "pk": pk, "name": f"BK {pk}", "markets": [
        {"id": 1, "key": "three_way", "raw_key": "1", "name": "Match Winner",
         "period": "full_time", "line": None, "team": None, "suspended": False,
         "outcomes": [{"key": "home", "name": "Home", "odds": price, "suspended": False}]},
    ]}


class FullBookmakerOddsSyncTests(TestCase):
    def setUp(self):
        self.match = Match.objects.create(external_id=862214, sync_scope="prematch")
        self.short = MatchOdds.objects.create(match=self.match, home_win_bet=2.5)
        self.payload = {"api_id": 862214, "odds": {
            "short": {"available": True, "home_win_bet": 7.0},
            "prematch": {"available": True, "updated_at": "2026-10-15T10:00:00Z",
                         "bookmakers": [bookmaker(), bookmaker(2, 2.05)]},
            "live": {"available": False, "updated_at": None, "bookmakers": []},
        }}
        self.provider = Mock()
        self.provider.fetch_game_odds.side_effect = lambda _: deepcopy(self.payload)
        self.service = MatchSyncService(provider=self.provider)

    def test_sync_stores_all_bookmakers_and_preserves_short_line(self):
        self.service.sync_match_bookmaker_odds(self.match)
        self.service.sync_match_bookmaker_odds(self.match)
        self.assertEqual(MatchOddsSnapshot.objects.count(), 2)
        self.assertEqual(MatchBookmakerOdds.objects.count(), 2)
        snapshot = self.match.odds_snapshots.get(scope="prematch")
        self.assertEqual(snapshot.raw_data, self.payload["odds"]["prematch"])
        self.assertEqual(snapshot.bookmakers.get(external_pk="1").markets, bookmaker()["markets"])
        self.short.refresh_from_db()
        self.assertEqual(self.short.home_win_bet, 2.5)

    def test_refresh_updates_price_and_removes_disappeared_bookmakers(self):
        self.service.sync_match_bookmaker_odds(self.match)
        self.payload["odds"]["prematch"]["bookmakers"] = [bookmaker(1, 2.2)]
        self.service.sync_match_bookmaker_odds(self.match)
        self.assertEqual(MatchBookmakerOdds.objects.count(), 1)
        self.assertEqual(MatchBookmakerOdds.objects.get().markets[0]["outcomes"][0]["odds"], 2.2)

    def test_registry_is_created_once_and_manual_artwork_is_preserved(self):
        self.service.sync_match_bookmaker_odds(self.match)
        brand = ComparisonBookmaker.objects.get(key="bk 1")
        brand.name = "Редакционное название"
        brand.icon = "game/bookmakers/bk1.png"
        brand.save()
        self.payload["odds"]["prematch"]["bookmakers"][0]["name"] = "  bk  1 "
        self.service.sync_match_bookmaker_odds(self.match)
        self.assertEqual(ComparisonBookmaker.objects.count(), 2)
        brand.refresh_from_db()
        self.assertEqual(brand.name, "Редакционное название")
        self.assertEqual(brand.icon.name, "game/bookmakers/bk1.png")

    def test_invalid_or_wrong_match_response_does_not_change_saved_data(self):
        self.service.sync_match_bookmaker_odds(self.match)
        valid = deepcopy(self.payload)
        for mutation in ("wrong_id", "invalid_price", "duplicate", "invalid_live"):
            self.payload = deepcopy(valid)
            if mutation == "wrong_id":
                self.payload["api_id"] = 123
            elif mutation == "invalid_price":
                self.payload["odds"]["prematch"]["bookmakers"][0]["markets"][0]["outcomes"][0]["odds"] = "NaN"
            elif mutation == "duplicate":
                self.payload["odds"]["prematch"]["bookmakers"].append(bookmaker())
            else:
                self.payload["odds"]["live"]["bookmakers"] = None
            with self.assertRaises(NeurokeffProviderError):
                self.service.sync_match_bookmaker_odds(self.match)
            self.assertEqual(MatchBookmakerOdds.objects.count(), 2)
            self.assertEqual(self.match.odds_snapshots.get(scope="prematch").raw_data, valid["odds"]["prematch"])

    def test_unavailable_retains_last_line_but_authoritative_empty_clears_it(self):
        self.service.sync_match_bookmaker_odds(self.match)
        block = self.payload["odds"]["prematch"]
        block.update(available=False, bookmakers=[])
        self.service.sync_match_bookmaker_odds(self.match)
        self.assertEqual(MatchBookmakerOdds.objects.count(), 2)
        self.assertFalse(self.match.odds_snapshots.get(scope="prematch").available)
        block["available"] = True
        self.service.sync_match_bookmaker_odds(self.match)
        self.assertEqual(MatchBookmakerOdds.objects.count(), 0)

    def test_older_provider_response_is_ignored(self):
        self.service.sync_match_bookmaker_odds(self.match)
        self.payload["odds"]["prematch"].update(updated_at="2026-10-14T10:00:00Z", bookmakers=[])
        result = self.service.sync_match_bookmaker_odds(self.match)
        self.assertEqual(result["scopes"]["prematch"]["reason"], "older_response")
        self.assertEqual(MatchBookmakerOdds.objects.count(), 2)

    def test_request_started_earlier_cannot_overwrite_newer_snapshot(self):
        self.service.sync_match_bookmaker_odds(self.match)
        snapshot = self.match.odds_snapshots.get(scope="prematch")
        with patch("game.services.match_sync.timezone.now", return_value=snapshot.requested_at - timedelta(seconds=1)):
            self.assertEqual(self.service.sync_match_bookmaker_odds(self.match)["scopes"]["prematch"]["reason"], "older_response")

    def test_live_and_finished_withdrawal_cannot_erase_prematch_archive(self):
        self.service.sync_match_bookmaker_odds(self.match)
        before = self.match.odds_snapshots.get(scope="prematch")
        block = self.payload["odds"]["prematch"]
        for phase in ("live", "finished"):
            self.match.sync_scope = phase
            self.match.save(update_fields=["sync_scope"])
            for available in (False, True):
                block.update(available=available, bookmakers=[], updated_at=None)
                result = self.service.sync_match_bookmaker_odds(self.match)
                self.assertEqual(result["scopes"]["prematch"]["reason"], "prematch_archive")
                after = self.match.odds_snapshots.get(scope="prematch")
                self.assertEqual(after.raw_data, before.raw_data)
                self.assertEqual(after.provider_updated_at, before.provider_updated_at)
                self.assertGreaterEqual(after.fetched_at, before.fetched_at)
                self.assertEqual(after.bookmakers.count(), 2)

    def test_missing_prematch_archive_can_be_loaded_after_finish_without_touching_short(self):
        self.match.sync_scope = "finished"
        self.match.save(update_fields=["sync_scope"])
        self.service.sync_match_bookmaker_odds(self.match)
        self.assertEqual(self.match.odds_snapshots.get(scope="prematch").bookmakers.count(), 2)
        self.short.refresh_from_db()
        self.assertEqual(self.short.home_win_bet, 2.5)

    def test_provider_failure_preserves_line(self):
        self.service.sync_match_bookmaker_odds(self.match)
        self.provider.fetch_game_odds.side_effect = NeurokeffProviderError("unavailable")
        with self.assertRaises(NeurokeffProviderError):
            self.service.sync_match_bookmaker_odds(self.match)
        self.assertEqual(MatchBookmakerOdds.objects.count(), 2)

    def test_suspended_null_price_is_preserved_but_unblocked_null_is_rejected(self):
        market = self.payload["odds"]["prematch"]["bookmakers"][0]["markets"][0]
        market["outcomes"][0].update(odds=None, suspended=True)
        self.service.sync_match_bookmaker_odds(self.match)
        stored = MatchBookmakerOdds.objects.get(external_pk="1").markets[0]["outcomes"][0]
        self.assertIsNone(stored["odds"])
        self.assertTrue(stored["suspended"])
        market["outcomes"][0]["suspended"] = False
        with self.assertRaises(NeurokeffProviderError):
            self.service.sync_match_bookmaker_odds(self.match)

    def test_task_handles_missing_match_and_uses_lock(self):
        self.assertEqual(refresh_match_bookmaker_odds(-1)["reason"], "match_not_found")
        with patch("game.tasks._run_locked", return_value={"status": "skipped"}) as lock:
            refresh_match_bookmaker_odds(self.match.pk)
            self.assertEqual(lock.call_args.args[0], f"match-full-odds:{self.match.pk}")

    def test_provider_uses_v2_endpoint_and_validates_response_type(self):
        provider = NeurokeffSportsProvider()
        with patch.object(provider, "_request", return_value=self.payload) as request:
            self.assertEqual(provider.fetch_game_odds(862214), self.payload)
            request.assert_called_once_with("/api/v2/games/odds", {"game_id": 862214}, timeout=5)
        with patch.object(provider, "_request", return_value=[]):
            with self.assertRaises(NeurokeffProviderError):
                provider.fetch_game_odds(862214)
