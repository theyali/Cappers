from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystFollow, User
from game.models import League, Match, Prediction, PredictionCoupon, Sport


class FollowingFeedTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(
            external_id=1201,
            code="football-feed-test",
            name="Football",
            name_ru="Футбол",
        )
        self.league = League.objects.create(
            external_id=1202,
            sport=self.sport,
            name="Feed League",
            name_ru="Лига ленты",
        )
        self.reader = User.objects.create_user(
            username="feed-reader",
            password="test-password",
            role=User.Role.READER,
        )
        self.followed = User.objects.create_user(
            username="followed-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.other = User.objects.create_user(
            username="other-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        AnalystFollow.objects.create(follower=self.reader, analyst=self.followed)

    def _prediction(self, *, author, external_id, state="", scope=Match.SyncScope.PREMATCH):
        match = Match.objects.create(
            external_id=external_id,
            sport=self.sport,
            league=self.league,
            sync_scope=scope,
            starts_at=timezone.now(),
            score="1-1" if scope == Match.SyncScope.LIVE else "",
            raw_data={
                "teams": {
                    "home": {"name": {"ru": "Хозяева"}},
                    "away": {"name": {"ru": "Гости"}},
                }
            },
        )
        coupon = PredictionCoupon.objects.create(
            author=author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=(
                PredictionCoupon.StateStatus.WIN
                if state == Prediction.StateStatus.WIN
                else PredictionCoupon.StateStatus.PENDING
            ),
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("190.00"),
            published_at=timezone.now(),
        )
        return Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="total",
            selection="ТБ 2.5",
            coefficient=Decimal("1.90"),
            stake=Decimal("100.00"),
            confidence=77,
            state_status=state,
        )

    def test_feed_requires_login(self):
        response = self.client.get(reverse("front:following_feed"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("cabinet:login"), response.url)

    def test_feed_contains_only_followed_cappers(self):
        followed_prediction = self._prediction(author=self.followed, external_id=1210)
        other_prediction = self._prediction(author=self.other, external_id=1211)
        self.client.force_login(self.reader)

        response = self.client.get(reverse("front:following_feed"))

        self.assertEqual(response.status_code, 200)
        ids = [item.id for item in response.context["page_obj"].object_list]
        self.assertEqual(ids, [followed_prediction.id])
        self.assertNotIn(other_prediction.id, ids)
        self.assertEqual(response.context["following_count"], 1)

    def test_feed_supports_live_and_status_filters(self):
        live_win = self._prediction(
            author=self.followed,
            external_id=1220,
            state=Prediction.StateStatus.WIN,
            scope=Match.SyncScope.LIVE,
        )
        self._prediction(
            author=self.followed,
            external_id=1221,
            state="",
            scope=Match.SyncScope.PREMATCH,
        )
        self.client.force_login(self.reader)

        response = self.client.get(
            reverse("front:following_feed"),
            {"live": "1", "status": Prediction.StateStatus.WIN},
        )

        self.assertEqual(response.status_code, 200)
        ids = [item.id for item in response.context["page_obj"].object_list]
        self.assertEqual(ids, [live_win.id])
        self.assertTrue(response.context["only_live"])
        self.assertEqual(response.context["active_status"], Prediction.StateStatus.WIN)
