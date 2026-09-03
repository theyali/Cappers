from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from front.models import PredictionFavorite, PredictionLike
from game.models import PredictionCoupon


class PredictionReactionGuardTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="reaction_analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.viewer = User.objects.create_user(
            username="reaction_viewer",
            password="safe-test-password",
        )
        self.coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("180.00"),
            confidence=70,
            published_at=timezone.now(),
        )
        self.like_url = reverse(
            "front:prediction_like",
            kwargs={"prediction_id": self.coupon.id},
        )
        self.favorite_url = reverse(
            "front:prediction_favorite",
            kwargs={"prediction_id": self.coupon.id},
        )

    def test_author_cannot_like_own_prediction(self):
        self.client.force_login(self.analyst)

        response = self.client.post(self.like_url)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(response.json()["active"])
        self.assertEqual(response.json()["count"], 0)
        self.assertFalse(
            PredictionLike.objects.filter(
                prediction=self.coupon,
                user=self.analyst,
            ).exists()
        )

    def test_author_cannot_favorite_own_prediction(self):
        self.client.force_login(self.analyst)

        response = self.client.post(self.favorite_url)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(response.json()["active"])
        self.assertEqual(response.json()["count"], 0)
        self.assertFalse(
            PredictionFavorite.objects.filter(
                prediction=self.coupon,
                user=self.analyst,
            ).exists()
        )

    def test_model_layer_rejects_own_reactions(self):
        with self.assertRaises(ValidationError):
            PredictionLike.objects.create(
                prediction=self.coupon,
                user=self.analyst,
            )

        with self.assertRaises(ValidationError):
            PredictionFavorite.objects.create(
                prediction=self.coupon,
                user=self.analyst,
            )

    def test_other_user_can_toggle_like_and_favorite(self):
        self.client.force_login(self.viewer)

        like_response = self.client.post(self.like_url)
        favorite_response = self.client.post(self.favorite_url)

        self.assertEqual(like_response.status_code, 200)
        self.assertTrue(like_response.json()["active"])
        self.assertEqual(like_response.json()["count"], 1)
        self.assertEqual(favorite_response.status_code, 200)
        self.assertTrue(favorite_response.json()["active"])
        self.assertEqual(favorite_response.json()["count"], 1)

        unlike_response = self.client.post(self.like_url)
        unfavorite_response = self.client.post(self.favorite_url)

        self.assertEqual(unlike_response.status_code, 200)
        self.assertFalse(unlike_response.json()["active"])
        self.assertEqual(unlike_response.json()["count"], 0)
        self.assertEqual(unfavorite_response.status_code, 200)
        self.assertFalse(unfavorite_response.json()["active"])
        self.assertEqual(unfavorite_response.json()["count"], 0)
