from decimal import Decimal

from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import RequestFactory, TestCase
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

    def _render_reactions(self, user):
        request = RequestFactory().get(
            reverse("front:prediction_detail", kwargs={"prediction_id": self.coupon.id})
        )
        request.user = user
        template = Template(
            "{% load prediction_reactions %}{% coupon_reactions coupon %}"
        )
        return template.render(Context({"request": request, "coupon": self.coupon}))

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

    def test_coupon_reactions_show_counts_and_disable_author_controls(self):
        PredictionLike.objects.create(prediction=self.coupon, user=self.viewer)
        PredictionFavorite.objects.create(prediction=self.coupon, user=self.viewer)

        html = self._render_reactions(self.analyst)

        self.assertIn("is-own-prediction", html)
        self.assertEqual(html.count('data-reaction-count'), 2)
        self.assertEqual(html.count('>1</b>'), 2)
        self.assertEqual(html.count('disabled aria-disabled="true"'), 2)

    def test_coupon_reactions_mark_viewer_reactions_active(self):
        PredictionLike.objects.create(prediction=self.coupon, user=self.viewer)
        PredictionFavorite.objects.create(prediction=self.coupon, user=self.viewer)

        html = self._render_reactions(self.viewer)

        self.assertIn("prediction-like is-active", html)
        self.assertIn("prediction-favorite is-active", html)
        self.assertNotIn('disabled aria-disabled="true"', html)
