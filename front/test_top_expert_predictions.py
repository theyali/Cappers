from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import League, Match, Prediction, PredictionCoupon, Sport


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class TopExpertPredictionsTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(
            external_id=19001,
            code="top-experts-football",
            name="Football",
            name_ru="Футбол",
        )
        self.league = League.objects.create(
            external_id=19002,
            sport=self.sport,
            name="Top Experts League",
            name_ru="Лига топовых экспертов",
        )

    def _analyst(self, username: str):
        user = User.objects.create_user(
            username=username,
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        profile = user.analyst_profile
        profile.is_public = True
        profile.save(update_fields=["is_public", "updated_at"])
        return user

    def _prediction(self, author, *, external_id: int, payout: str):
        match = Match.objects.create(
            external_id=external_id,
            sport=self.sport,
            league=self.league,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now(),
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
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal(payout),
            confidence=80,
            published_at=timezone.now(),
            settled_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="П1",
            coefficient=Decimal("2.00"),
            stake=Decimal("100.00"),
            state_status=Prediction.StateStatus.WIN,
        )
        return coupon

    def test_top_experts_tab_uses_first_ten_from_cappers_ranking(self):
        authors = []
        for index in range(11):
            author = self._analyst(f"ranked-expert-{index:02d}")
            authors.append(author)
            self._prediction(
                author,
                external_id=19100 + index,
                payout=f"{110 + index * 10}.00",
            )

        catalog_response = self.client.get(reverse("front:cappers_stats"))
        response = self.client.get(reverse("front:predictions"), {"top": "1"})

        self.assertEqual(catalog_response.status_code, 200)
        self.assertEqual(response.status_code, 200)

        expected_ids = {
            expert["id"] for expert in catalog_response.context["experts"][:10]
        }
        actual_ids = {
            item.coupon.author_id for item in response.context["page_obj"].object_list
        }

        self.assertEqual(actual_ids, expected_ids)
        self.assertEqual(response.context["filtered_predictions"], 10)
        self.assertTrue(response.context["top_experts_only"])
        self.assertTrue(response.context["top_experts_tab"]["active"])
        self.assertEqual(response.context["top_experts_tab"]["count"], 10)
        self.assertNotIn(authors[0].id, actual_ids)

        html = response.content.decode()
        self.assertIn('data-top-experts-tab', html)
        self.assertIn('predictions-tab-top is-active', html)
        self.assertIn('predictions-tab-top-icon', html)
        self.assertIn('Топовые эксперты', html)
        self.assertIn("front/css/main.css", html)
        self.assertIn('<input type="hidden" name="top" value="1">', html)
        self.assertTrue(all("top=1" in tab["href"] for tab in response.context["status_tabs"]))

    def test_top_experts_tab_preserves_filters_and_can_be_toggled_off(self):
        author = self._analyst("single-ranked-expert")
        self._prediction(author, external_id=19200, payout="180.00")

        response = self.client.get(
            reverse("front:predictions_by_sport", kwargs={"sport_code": self.sport.code}),
            {"top": "1", "sort": "roi"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["top_experts_tab"]["active"])
        toggle_href = response.context["top_experts_tab"]["href"]
        self.assertIn(f"/predictions/{self.sport.code}/", toggle_href)
        self.assertIn("sort=roi", toggle_href)
        self.assertNotIn("top=1", toggle_href)
        self.assertIn("top=1", response.context["pagination_query"])
