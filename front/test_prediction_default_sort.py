from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystFollow, User
from game.models import Match, Prediction, PredictionCoupon, Sport


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class PredictionDefaultSortTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(
            external_id=99001,
            code="default-sort-test",
            name="Default sort test",
            name_ru="Тест сортировки",
        )
        self.followed_analyst = User.objects.create_user(
            username="followed-sort-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.fresh_analyst = User.objects.create_user(
            username="fresh-sort-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(
            username="sort-reader",
            password="test-password",
            role=User.Role.READER,
        )
        AnalystFollow.objects.create(
            follower=self.reader,
            analyst=self.followed_analyst,
        )

    def _coupon(self, *, author, external_id, published_at):
        match = Match.objects.create(
            external_id=external_id,
            sport=self.sport,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={},
        )
        coupon = PredictionCoupon.objects.create(
            author=author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=70,
            published_at=published_at,
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="П1",
            coefficient=Decimal("2.00"),
            stake=Decimal("100.00"),
            state_status="",
        )
        return coupon

    def test_default_sort_shows_freshest_first_for_authenticated_user(self):
        now = timezone.now()
        older_followed = self._coupon(
            author=self.followed_analyst,
            external_id=99011,
            published_at=now - timedelta(hours=2),
        )
        newest = self._coupon(
            author=self.fresh_analyst,
            external_id=99012,
            published_at=now,
        )

        self.client.force_login(self.reader)
        response = self.client.get(reverse("front:predictions"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_sort"], "new")
        ids = [item.id for item in response.context["page_obj"].object_list]
        self.assertEqual(ids[:2], [newest.id, older_followed.id])

    def test_default_sort_limits_long_author_streaks_on_page(self):
        now = timezone.now()
        quiet_analyst = User.objects.create_user(
            username="quiet-sort-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        dominant_coupons = [
            self._coupon(
                author=self.fresh_analyst,
                external_id=99100 + index,
                published_at=now - timedelta(minutes=index),
            )
            for index in range(5)
        ]
        other_coupons = [
            self._coupon(
                author=quiet_analyst,
                external_id=99200 + index,
                published_at=now - timedelta(hours=1, minutes=index),
            )
            for index in range(2)
        ]

        response = self.client.get(reverse("front:predictions"))

        self.assertEqual(response.status_code, 200)
        cards = list(response.context["page_obj"].object_list)
        self.assertEqual(
            {card.id for card in cards},
            {coupon.id for coupon in dominant_coupons + other_coupons},
        )
        max_streak = 1
        current_streak = 1
        previous_author_id = None
        for card in cards:
            author_id = card.coupon.author_id
            if author_id == previous_author_id:
                current_streak += 1
            else:
                current_streak = 1
            max_streak = max(max_streak, current_streak)
            previous_author_id = author_id
        self.assertLessEqual(max_streak, 3)
