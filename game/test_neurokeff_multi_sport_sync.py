from django.test import TestCase

from game.models import Match
from game.services.match_sync import MatchSyncService
from game.services.providers.neurokeff import NeurokeffSportsProvider


class MultiSportProviderTests(TestCase):
    def test_provider_fetches_live_matches_for_each_configured_sport(self):
        provider = RecordingProvider(
            sports=[
                {"code": "football", "id": 2, "name": "Football", "name_ru": "Футбол"},
                {"code": "hockey", "id": 4, "name": "Hockey", "name_ru": "Хоккей"},
            ]
        )

        payloads = provider.fetch_live_matches()

        self.assertEqual([call["sport_id"] for call in provider.calls], [2, 4])
        self.assertEqual([payload["_sport_meta"]["code"] for payload in payloads], ["football", "hockey"])


class MultiSportSyncTests(TestCase):
    def test_match_sync_uses_payload_sport_meta_and_generic_bookmaker_odds(self):
        provider = FakeUpcomingProvider(
            [
                {
                    "id": 990001,
                    "sport_id": 3,
                    "_sport_meta": {
                        "code": "basketball",
                        "id": 3,
                        "name": "Basketball",
                        "name_ru": "Баскетбол",
                    },
                    "time_status": "0",
                    "game_date_time": "2026-08-29T20:00:00+04:00",
                    "score": "",
                    "odds": {
                        "bookmakers": [
                            {
                                "name": "Bookmaker",
                                "bets": [
                                    {
                                        "name": "Match Winner",
                                        "values": [
                                            {"value": "Home", "odd": "1.85"},
                                            {"value": "Away", "odd": "1.95"},
                                        ],
                                    },
                                    {
                                        "name": "Totals",
                                        "values": [
                                            {"value": "Over", "line": "2.5", "odd": "1.91"},
                                            {"value": "Under", "line": "2.5", "odd": "1.89"},
                                        ],
                                    },
                                ],
                            }
                        ]
                    },
                }
            ]
        )

        result = MatchSyncService(provider=provider).sync_upcoming()

        match = Match.objects.select_related("sport", "odds").get(external_id=990001)
        self.assertEqual(result["created"], 1)
        self.assertEqual(match.sport.code, "basketball")
        self.assertEqual(match.sport.name_ru, "Баскетбол")
        self.assertEqual(match.odds.home_win_bet, 1.85)
        self.assertEqual(match.odds.away_win_bet, 1.95)
        self.assertEqual(match.odds.goals_over_2_5, 1.91)
        self.assertEqual(match.odds.totals_all["Over 2.5"], 1.91)


class RecordingProvider(NeurokeffSportsProvider):
    def __init__(self, sports):
        super().__init__(sports=sports)
        self.calls = []

    def _get_paginated(self, endpoint, params):
        self.calls.append(params)
        return [{"id": params["sport_id"]}]


class FakeUpcomingProvider:
    def __init__(self, payloads):
        self.payloads = payloads

    def fetch_upcoming_matches(self):
        return self.payloads
