from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystFollow, User
from game.models import Match, Prediction, PredictionCoupon, Sport


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
