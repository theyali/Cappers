from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from back.templatetags.site_extras import latest_prediction_cards, my_recent_coupons
from cabinet.models import User
from game.models import Match, PredictionCoupon, PredictionItem


class LatestPredictionCardsTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="sidebar_prediction_analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.matches = [
            Match.objects.create(
                external_id=991000 + index,
                sync_scope=Match.SyncScope.PREMATCH,
            )
            for index in range(1, 5)
        ]

    def _add_item(self, coupon, match, selection):
        return PredictionItem.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection=selection,
            coefficient=Decimal("2.00"),
            stake=Decimal("10.00"),
        )

    def test_coupon_with_many_matches_is_one_sidebar_prediction(self):
        multi = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("80.00"),
            confidence=83,
            published_at=timezone.now(),
        )
        self._add_item(multi, self.matches[0], "Хозяева")
        self._add_item(multi, self.matches[1], "Гости")
        self._add_item(multi, self.matches[2], "Ничья")

        single = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("20.00"),
            confidence=61,
            published_at=timezone.now(),
        )
        self._add_item(single, self.matches[3], "Хозяева")

        cards = latest_prediction_cards()

        self.assertEqual(len(cards), 2)
        self.assertEqual({card.id for card in cards}, {multi.id, single.id})

        multi_card = next(card for card in cards if card.id == multi.id)
        self.assertEqual(multi_card.positions_count, 3)
        self.assertEqual(multi_card.market, "Экспресс · 3 игр")
        self.assertEqual(multi_card.selection, "Хозяева + ещё 2")
        self.assertEqual(multi_card.coefficient, Decimal("8.00"))
        self.assertEqual(multi_card.coupon.confidence, 83)

    def test_drafts_are_not_shown_as_latest_predictions(self):
        draft = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("20.00"),
            confidence=70,
        )
        self._add_item(draft, self.matches[0], "Хозяева")

        self.assertEqual(latest_prediction_cards(), [])

    def test_my_recent_coupons_only_contains_published_coupons(self):
        draft = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("30.00"),
            confidence=55,
        )
        self._add_item(draft, self.matches[0], "Черновик")

        published = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("20.00"),
            possible_payout=Decimal("50.00"),
            confidence=74,
            published_at=timezone.now(),
        )
        self._add_item(published, self.matches[1], "Опубликован")

        context = my_recent_coupons(self.analyst)
        coupons = context["my_coupons"]

        self.assertEqual([coupon.id for coupon in coupons], [published.id])
        self.assertEqual(coupons[0].predictions_count, 1)
        self.assertEqual(coupons[0].sidebar_coefficient, Decimal("2.50"))
        self.assertEqual(coupons[0].sidebar_date, published.published_at)
