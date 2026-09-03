from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from cabinet.models import AnalystPaidPlan, User
from game.models import PredictionCoupon
from game.views import _parse_coupon_audience


class PredictionAudienceTests(TestCase):
    def test_default_audience_is_free(self):
        analyst = User.objects.create_user(
            username="audience-free",
            password="test-password",
            role=User.Role.ANALYST,
        )

        audience = _parse_coupon_audience("", analyst)

        self.assertEqual(audience, PredictionCoupon.Audience.FREE)

    def test_paid_audience_requires_active_paid_plan(self):
        analyst = User.objects.create_user(
            username="audience-no-plan",
            password="test-password",
            role=User.Role.ANALYST,
        )
        profile = analyst.analyst_profile
        profile.paid_predictions_enabled = True
        profile.paid_predictions_price = Decimal("0")
        profile.save(
            update_fields=[
                "paid_predictions_enabled",
                "paid_predictions_price",
                "updated_at",
            ]
        )

        with self.assertRaises(ValidationError):
            _parse_coupon_audience(PredictionCoupon.Audience.PAID, analyst)

    def test_paid_audience_is_allowed_with_active_paid_plan(self):
        analyst = User.objects.create_user(
            username="audience-with-plan",
            password="test-password",
            role=User.Role.ANALYST,
        )
        profile = analyst.analyst_profile
        profile.paid_predictions_enabled = True
        profile.save(update_fields=["paid_predictions_enabled", "updated_at"])
        AnalystPaidPlan.objects.create(
            analyst=analyst,
            title="7 дней",
            duration_days=7,
            price=Decimal("700.00"),
        )

        audience = _parse_coupon_audience(PredictionCoupon.Audience.PAID, analyst)

        self.assertEqual(audience, PredictionCoupon.Audience.PAID)
