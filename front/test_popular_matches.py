from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import League, Match, MatchOdds, Prediction, PredictionCoupon, Sport, Team

from .popular_matches import build_popular_matches


class PopularMatchesTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(
            external_id=91001,
            code="popular-football",
            name="Football",
            name_ru="Футбол",
        )
        self.home = Team.objects.create(
            external_id=91002,
            sport=self.sport,
            name="Home Team",
            name_ru="Хозяева",
        )
        self.away = Team.objects.create(
            external_id=91003,
            sport=self.sport,
            name="Away Team",
            name_ru="Гости",
        )
        self.author = User.objects.create_user(
            username="popular-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self._external_id = 92000

    def _league(self, name, rating=0):
        self._external_id += 1
        return League.objects.create(
            external_id=self._external_id,
            sport=self.sport,
            name=name,
            name_ru=name,
            raw_data={"rating": rating},
        )

    def _match(self, league, hours):
        self._external_id += 1
        return Match.objects.create(
            external_id=self._external_id,
            sport=self.sport,
            league=league,
            home_team=self.home,
            away_team=self.away,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=hours),
        )

    def _publish_prediction(self, match):
        coupon = PredictionCoupon.objects.create(
            author=self.author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("190.00"),
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="П1",
            coefficient=Decimal("1.90"),
            stake=Decimal("100.00"),
        )

    def test_selection_prefers_league_rating_then_predictions_then_odds(self):
        high = self._match(self._league("High", 10), 5)
        lower = self._match(self._league("Lower", 3), 1)

        predicted = self._match(self._league("Predicted", 0), 2)
        self._publish_prediction(predicted)

        odds_first = self._match(self._league("Odds first", 0), 3)
        MatchOdds.objects.create(match=odds_first, home_win_bet=1.85)
        odds_second = self._match(self._league("Odds second", 0), 4)
        MatchOdds.objects.create(match=odds_second, away_win_bet=2.10)

        ignored = self._match(self._league("Ignored", 0), 0.5)

        items = build_popular_matches(limit=5)
        ids = [item.id for item in items]

        self.assertEqual(ids, [high.id, lower.id, predicted.id, odds_first.id, odds_second.id])
        self.assertNotIn(ignored.id, ids)
        self.assertEqual(items[0].league_rating, 10.0)

    def test_cappers_page_renders_reusable_popular_matches_block(self):
        match = self._match(self._league("Premier", 7), 1)

        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('class="popular_matches"', html)
        self.assertIn("Популярные матчи", html)
        self.assertIn(match.get_absolute_url(), html)
        self.assertIn("front/css/popular-matches.css", html)
        self.assertIn('class="cappers-side-column"', html)
