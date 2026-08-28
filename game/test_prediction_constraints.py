from django.test import SimpleTestCase
from django.urls import resolve, reverse

from .prediction_constraints import _validate_payload_limits, create_coupon


class PredictionConstraintTests(SimpleTestCase):
    def test_coupon_route_uses_constraint_wrapper(self):
        match = resolve(reverse("game:create_coupon"))
        self.assertIs(match.func, create_coupon)

    def test_coefficient_one_is_rejected(self):
        error = _validate_payload_limits(
            {
                "stake": "100",
                "items": [{"coefficient": "1.00"}],
            }
        )
        self.assertIn("Коэффициент 1.00", error)

    def test_coefficient_above_one_is_allowed(self):
        error = _validate_payload_limits(
            {
                "stake": "100",
                "items": [{"coefficient": "1.01"}],
            }
        )
        self.assertEqual(error, "")

    def test_minimum_stake_is_enforced_for_publish(self):
        error = _validate_payload_limits(
            {
                "stake": "99",
                "items": [{"coefficient": "1.50"}],
            }
        )
        self.assertEqual(error, "Минимальная сумма прогноза — 100 ₽.")

    def test_maximum_stake_is_enforced_for_publish(self):
        error = _validate_payload_limits(
            {
                "stake": "1000001",
                "items": [{"coefficient": "1.50"}],
            }
        )
        self.assertEqual(error, "Максимальная сумма прогноза — 1 000 000 ₽.")

    def test_draft_autosave_allows_partial_stake_while_user_is_typing(self):
        error = _validate_payload_limits(
            {
                "autosave": True,
                "stake": "9",
                "items": [{"coefficient": "1.50"}],
            }
        )
        self.assertEqual(error, "")
