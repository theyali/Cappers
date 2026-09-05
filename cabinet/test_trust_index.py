from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from game.models import PredictionCoupon

from .models import AnalystProfile, User
from .trust_index import calculate_capper_trust_index, refresh_capper_trust_index


class CapperTrustIndexTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="trust_expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.profile = AnalystProfile.objects.get(user=self.analyst)

    def _moment(self, year: int, month: int, day: int):
        value = datetime(year, month, day, 12, 0, 0)
        if timezone.is_aware(timezone.now()):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value

    def _coupon(
        self,
        state: str,
        *,
        stake: str = "100",
        payout: str = "200",
        confidence: int = 70,
        published_at=None,
        analyst=None,
    ) -> PredictionCoupon:
        published_at = published_at or timezone.now()
        return PredictionCoupon.objects.create(
            author=analyst or self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=state,
            total_stake=Decimal(stake),
            possible_payout=Decimal(payout),
            confidence=confidence,
            published_at=published_at,
            settled_at=published_at if state != PredictionCoupon.StateStatus.PENDING else None,
        )

    def test_no_settled_history_returns_zero_index(self):
        result = calculate_capper_trust_index(self.analyst.pk)

        self.assertEqual(result.trust_index, Decimal("0.0"))
        self.assertEqual(result.metrics["settled_count"], 0)

    def test_small_sample_caps_high_raw_score(self):
        for day in range(1, 5):
            self._coupon(
                PredictionCoupon.StateStatus.WIN,
                confidence=100,
                published_at=timezone.now() - timedelta(days=day),
            )

        result = calculate_capper_trust_index(self.analyst.pk)

        self.assertEqual(result.metrics["settled_count"], 4)
        self.assertEqual(result.trust_index, Decimal("4.0"))
        self.assertGreater(result.components["roi"], Decimal("0.0"))
        self.assertGreater(result.components["confidence"], Decimal("0.0"))

    def test_refresh_persists_index_and_timestamp(self):
        self._coupon(
            PredictionCoupon.StateStatus.WIN,
            confidence=100,
            published_at=timezone.now() - timedelta(days=1),
        )

        profile = refresh_capper_trust_index(self.analyst.pk)

        self.assertIsNotNone(profile)
        self.assertEqual(profile.trust_index, Decimal("4.0"))
        self.assertIsNotNone(profile.trust_index_updated_at)

    def test_coupon_save_and_delete_refresh_profile_index(self):
        coupon = self._coupon(
            PredictionCoupon.StateStatus.PENDING,
            confidence=100,
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.trust_index, Decimal("0.0"))

        coupon.state_status = PredictionCoupon.StateStatus.WIN
        coupon.settled_at = timezone.now()
        coupon.save(update_fields=["state_status", "settled_at", "updated_at"])

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.trust_index, Decimal("4.0"))
        self.assertIsNotNone(self.profile.trust_index_updated_at)

        coupon.delete()

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.trust_index, Decimal("0.0"))

    def test_stability_uses_neutral_score_until_two_active_months_exist(self):
        self._coupon(
            PredictionCoupon.StateStatus.WIN,
            published_at=self._moment(2026, 8, 1),
        )
        self._coupon(
            PredictionCoupon.StateStatus.LOSE,
            published_at=self._moment(2026, 8, 2),
            payout="190",
        )

        result = calculate_capper_trust_index(self.analyst.pk)

        self.assertEqual(result.components["stability"], Decimal("5.0"))
