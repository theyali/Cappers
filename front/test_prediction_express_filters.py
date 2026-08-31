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
class PredictionExpressFiltersTests(TestCase):
    def setUp(self):
        self.football = Sport.objects.create(
            external_id=28001,
            code="football",
            name="Football",
            name_ru="Футбол",
        )
        self.tennis = Sport.objects.create(
            external_id=28002,
            code="tennis",
            name="Tennis",
            name_ru="Теннис",
        )
        self.football_league = League.objects.create(
            external_id=28101,
            sport=self.football,
            name="Football League",
            name_ru="Футбольная лига",
        )
        self.tennis_league = League.objects.create(
            external_id=28102,
            sport=self.tennis,
            name="Tennis League",
            name_ru="Теннисная лига",
        )
        self.author = User.objects.create_user(
            username="express-filter-expert",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        profile = self.author.analyst_profile
        profile.is_public = True
        profile.save(update_fields=["is_public", "updated_at"])

        self.football_match = self._match(
            28201,
            self.football,
            self.football_league,
            "Футбол Хозяева",
            "Футбол Гости",
        )
        self.tennis_match = self._match(
            28202,
            self.tennis,
            self.tennis_league,
            "Теннис Хозяева",
            "Теннис Гости",
        )
        self.second_tennis_match = self._match(
            28203,
            self.tennis,
            self.tennis_league,
            "Теннис 2 Хозяева",
            "Теннис 2 Гости",
        )

        self.football_single = self._coupon(self.football_match)
        self.tennis_single = self._coupon(self.tennis_match)
        self.mixed_express = self._coupon(self.football_match, self.tennis_match)
        self.tennis_express = self._coupon(self.tennis_match, self.second_tennis_match)

    def _match(self, external_id, sport, league, home_name, away_name):
        return Match.objects.create(
            external_id=external_id,
            sport=sport,
            league=league,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now(),
            raw_data={
                "teams": {
                    "home": {"name": {"ru": home_name}},
                    "away": {"name": {"ru": away_name}},
                }
            },
        )

    def _coupon(self, *matches):
        coupon = PredictionCoupon.objects.create(
            author=self.author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("250.00"),
            confidence=75,
            published_at=timezone.now(),
        )
        for index, match in enumerate(matches, start=1):
            Prediction.objects.create(
                coupon=coupon,
                match=match,
                market="winner",
                selection=f"П{index}",
                coefficient=Decimal("1.50"),
                stake=Decimal("100.00"),
                state_status=Prediction.StateStatus.PENDING,
            )
        return coupon

    @staticmethod
    def _coupon_ids(response):
        return {card.coupon.id for card in response.context["page_obj"].object_list}

    def test_sport_pages_show_only_single_match_predictions(self):
        football_response = self.client.get(
            reverse("front:predictions_by_sport", kwargs={"sport_code": "football"})
        )
        tennis_response = self.client.get(
            reverse("front:predictions_by_sport", kwargs={"sport_code": "tennis"})
        )

        self.assertEqual(football_response.status_code, 200)
        self.assertEqual(tennis_response.status_code, 200)
        self.assertEqual(self._coupon_ids(football_response), {self.football_single.id})
        self.assertEqual(self._coupon_ids(tennis_response), {self.tennis_single.id})
        self.assertNotIn(self.mixed_express.id, self._coupon_ids(football_response))
        self.assertNotIn(self.mixed_express.id, self._coupon_ids(tennis_response))
        self.assertNotIn(self.tennis_express.id, self._coupon_ids(tennis_response))

    def test_express_route_contains_all_multi_match_coupons(self):
        response = self.client.get(reverse("front:prediction_expresses"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["express_only"])
        self.assertEqual(
            self._coupon_ids(response),
            {self.mixed_express.id, self.tennis_express.id},
        )
        self.assertEqual(response.context["page_heading"], "Экспрессы")

        express_tab = next(
            tab for tab in response.context["sport_tabs"] if tab["code"] == "express"
        )
        tennis_tab = next(
            tab for tab in response.context["sport_tabs"] if tab["code"] == "tennis"
        )
        football_tab = next(
            tab for tab in response.context["sport_tabs"] if tab["code"] == "football"
        )
        self.assertTrue(express_tab["active"])
        self.assertEqual(express_tab["count"], 2)
        self.assertEqual(tennis_tab["count"], 1)
        self.assertEqual(football_tab["count"], 1)

    def test_all_predictions_keeps_singles_and_expresses(self):
        response = self.client.get(reverse("front:predictions"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._coupon_ids(response),
            {
                self.football_single.id,
                self.tennis_single.id,
                self.mixed_express.id,
                self.tennis_express.id,
            },
        )

    def test_multi_match_detail_is_named_express_and_uses_compact_slip(self):
        express_response = self.client.get(
            reverse("front:prediction_detail", args=[self.mixed_express.id])
        )
        single_response = self.client.get(
            reverse("front:prediction_detail", args=[self.tennis_single.id])
        )

        self.assertEqual(express_response.status_code, 200)
        self.assertContains(express_response, f"Экспресс #{self.mixed_express.id}")
        self.assertContains(express_response, "Публичный экспресс")
        self.assertContains(express_response, 'class="coupon-slip is-compact"')

        self.assertEqual(single_response.status_code, 200)
        self.assertContains(single_response, f"Купон #{self.tennis_single.id}")
        self.assertNotContains(single_response, "Публичный экспресс")
