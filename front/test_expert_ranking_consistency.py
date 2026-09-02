from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import PredictionCoupon


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class SharedExpertRankingTests(TestCase):
    def _analyst(self, username):
        user = User.objects.create_user(
            username=username,
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        profile = user.analyst_profile
        profile.is_public = True
        profile.save(update_fields=["is_public", "updated_at"])
        return user

    def _coupon(self, author, *, state, stake="100.00", payout="100.00"):
        return PredictionCoupon.objects.create(
            author=author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=state,
            total_stake=Decimal(stake),
            possible_payout=Decimal(payout),
            published_at=timezone.now(),
            settled_at=(
                timezone.now()
                if state
                in {
                    PredictionCoupon.StateStatus.WIN,
                    PredictionCoupon.StateStatus.LOSE,
                    PredictionCoupon.StateStatus.REFUND,
                }
                else None
            ),
        )

    def test_catalog_and_home_use_the_same_expert_order(self):
        history = self._analyst("history-expert")
        lucky = self._analyst("lucky-expert")
        admin = self._analyst("admin")

        # 20% ROI over a real history: ranking score 10% after shrinkage.
        for _ in range(10):
            self._coupon(
                history,
                state=PredictionCoupon.StateStatus.WIN,
                payout="120.00",
            )

        # 100% ROI on a single result: ranking score is only about 9.09%.
        self._coupon(
            lucky,
            state=PredictionCoupon.StateStatus.WIN,
            payout="200.00",
        )

        # Lots of fresh activity must not put admin above proven experts.
        for _ in range(15):
            self._coupon(
                admin,
                state=PredictionCoupon.StateStatus.PENDING,
                payout="150.00",
            )

        catalog_response = self.client.get(reverse("front:cappers_stats"))
        home_response = self.client.get(reverse("front:index"))

        self.assertEqual(catalog_response.status_code, 200)
        self.assertEqual(home_response.status_code, 200)

        catalog_ids = [expert["id"] for expert in catalog_response.context["experts"]]
        home_ids = [expert["id"] for expert in home_response.context["best_experts"]]

        self.assertEqual(home_ids, catalog_ids[: len(home_ids)])
        self.assertEqual(catalog_ids[:3], [history.id, lucky.id, admin.id])


@override_settings(STORAGES=TEST_STORAGES)
class FavoritesEmptyStateTests(TestCase):
    def test_empty_favorites_uses_site_logo(self):
        user = User.objects.create_user(
            username="favorites-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("front:favorites"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="favorites-empty-logo"')
        self.assertContains(response, "/static/front/img/logo.png")
        self.assertContains(response, "Избранных прогнозов пока нет")
