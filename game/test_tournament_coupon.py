import json
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User, UserVipSubscription
from game.models import Match, MatchOdds, Prediction, PredictionCoupon, Sport
from game.services.prediction_editor import update_rich_prediction
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant
from tournaments.services.coupons import TOURNAMENT_QUICK_PUBLISH_MESSAGE
from tournaments.testing import create_money_prizes


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
LONG_DESCRIPTION = "Хозяева сильнее на своём поле и лучше закрывают фланги. " * 8


@override_settings(STORAGES=TEST_STORAGES)
class TournamentCouponFlowTests(TestCase):
    def setUp(self):
        self.football = Sport.objects.create(external_id=1001, code="football", name="Football", name_ru="Футбол")
        self.analyst = User.objects.create_user(
            username="cup-capper", password="safe-test-password", role=User.Role.ANALYST,
        )
        self.tournament = Tournament.objects.create(
            title="Coupon Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=3),
            min_coefficient=Decimal("1.80"),
        )
        create_money_prizes(self.tournament, "1000.00", "500.00", "250.00")
        self.tournament.allowed_sports.add(self.football)
        TournamentParticipant.objects.create(tournament=self.tournament, user=self.analyst)
        self.match = Match.objects.create(
            external_id=774001,
            sport=self.football,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=2),
            raw_data={"teams": {"home": {"name": {"ru": "Арсенал"}}, "away": {"name": {"ru": "Челси"}}}},
        )
        MatchOdds.objects.create(match=self.match, home_win_bet=1.85)
        self.coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            prediction_format=PredictionCoupon.PredictionFormat.QUICK,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            total_stake=Decimal("500"),
            possible_payout=Decimal("925.00"),
            confidence=70,
        )
        Prediction.objects.create(
            coupon=self.coupon, match=self.match, market="winner", selection="Арсенал",
            coefficient=Decimal("1.85"), stake=Decimal("500"),
        )
        self.client.force_login(self.analyst)

    def _coupon_request(self, **overrides):
        self.coupon.refresh_from_db()
        payload = {
            "autosave": True,
            "coupon_id": self.coupon.pk,
            "base_revision": self.coupon.updated_at.isoformat(),
            "stake": "500",
            "confidence": 70,
            "tournament_id": self.tournament.pk,
            "items": [{"match_id": self.match.pk, "market": "winner", "selection": "Арсенал", "coefficient": "1.85"}],
        }
        payload.update(overrides)
        return self.client.post(reverse("game:create_coupon"), json.dumps(payload), content_type="application/json")

    def _publish(self, **overrides):
        data = {
            "total_stake": "500",
            "confidence": "70",
            "headline": "Арсенал дома сильнее",
            "description": LONG_DESCRIPTION,
            "tournament": str(self.tournament.pk),
            "published_status": PredictionCoupon.PublishedStatus.PUBLISHED,
        }
        data.update(overrides)
        return self.client.post(reverse("game:rich_prediction_create"), data)

    def test_draft_keeps_tournament_and_quick_publish_is_refused(self):
        response = self._coupon_request()
        self.assertEqual(response.status_code, 200, response.content)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.tournament, self.tournament)
        draft = self.client.get(reverse("game:coupon_draft_state")).json()["draft"]
        self.assertEqual(draft["tournament_id"], self.tournament.pk)
        self.assertEqual(draft["items"][0]["sport"], "football")

        response = self._coupon_request(autosave=False)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], TOURNAMENT_QUICK_PUBLISH_MESSAGE)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)

    def test_unavailable_tournament_is_dropped_on_autosave_and_refused_on_publish(self):
        self.coupon.tournament = self.tournament
        self.coupon.save(update_fields=["tournament"])
        TournamentParticipant.objects.filter(user=self.analyst).delete()

        self.assertEqual(self._coupon_request().status_code, 200)
        self.coupon.refresh_from_db()
        self.assertIsNone(self.coupon.tournament)
        self.assertEqual(self._coupon_request(autosave=False).status_code, 400)

    def test_participant_without_vip_publishes_tournament_prediction_with_text(self):
        self.assertEqual(self.client.get(reverse("game:rich_prediction_create")).status_code, 200)

        response = self._publish()

        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(self.coupon.prediction_format, PredictionCoupon.PredictionFormat.RICH)
        self.assertTrue(TournamentCoupon.objects.filter(tournament=self.tournament, coupon=self.coupon).exists())

    def test_tournament_prediction_requires_title_and_long_description(self):
        for overrides, field in (({"headline": ""}, "headline"), ({"description": "Коротко"}, "description")):
            response = self._publish(**overrides)
            self.assertEqual(response.status_code, 200)
            self.assertIn(field, response.context["form"].errors)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertFalse(TournamentCoupon.objects.exists())

    def test_rule_violation_rolls_back_publication(self):
        self.tournament.min_coefficient = Decimal("2.00")
        self.tournament.save(update_fields=["min_coefficient"])

        response = self._publish()

        self.assertEqual(response.status_code, 200)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertFalse(TournamentCoupon.objects.exists())
        self.analyst.coin_wallet.refresh_from_db()
        self.assertEqual(self.analyst.coin_wallet.balance, 1000)

    def test_non_vip_cannot_publish_without_tournament(self):
        response = self._publish(tournament="")
        self.assertEqual(response.status_code, 200)
        self.assertIn("tournament", response.context["form"].errors)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)

    def test_editor_hides_access_choice_for_tournament_draft(self):
        self.coupon.tournament = self.tournament
        self.coupon.save(update_fields=["tournament"])
        response = self.client.get(reverse("game:rich_prediction_create"))
        self.assertContains(response, "data-rich-access-card data-tournament-hidden hidden")

    def _published(self):
        self.assertEqual(self._publish().status_code, 302)
        self.coupon.refresh_from_db()
        return self.coupon

    def _edit_data(self, coupon, **overrides):
        data = {
            "total_stake": str(coupon.total_stake),
            "confidence": str(coupon.confidence),
            "headline": coupon.headline,
            "description": coupon.description,
            "published_status": PredictionCoupon.PublishedStatus.PUBLISHED,
        }
        data.update(overrides)
        return data

    def test_published_tournament_prediction_keeps_confidence_and_text(self):
        coupon = self._published()
        for overrides, field in (
            ({"confidence": "5"}, "confidence"),
            ({"headline": ""}, "headline"),
            ({"description": ""}, "description"),
        ):
            with self.assertRaises(ValidationError) as caught:
                update_rich_prediction(self.analyst, coupon, self._edit_data(coupon, **overrides), {})
            self.assertIn(field, caught.exception.message_dict)
        coupon.refresh_from_db()
        self.assertEqual(coupon.confidence, 70)
        self.assertTrue(coupon.headline)

    def test_editing_settled_prediction_keeps_its_payout(self):
        coupon = self._published()
        PredictionCoupon.objects.filter(pk=coupon.pk).update(
            state_status=PredictionCoupon.StateStatus.WIN, possible_payout=Decimal("500.00"),
        )
        coupon.refresh_from_db()

        update_rich_prediction(self.analyst, coupon, self._edit_data(coupon, headline="Новый заголовок"), {})

        coupon.refresh_from_db()
        self.assertEqual(coupon.headline, "Новый заголовок")
        self.assertEqual(coupon.possible_payout, Decimal("500.00"))

    def test_author_edits_tournament_prediction_after_the_tournament(self):
        coupon = self._published()
        Tournament.objects.filter(pk=self.tournament.pk).update(
            starts_at=timezone.now() - timedelta(days=3), ends_at=timezone.now() - timedelta(minutes=1),
        )
        url = reverse("game:rich_prediction_edit", kwargs={"coupon_id": coupon.pk})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse("game:rich_prediction_create")).status_code, 403)

    def test_stale_draft_tournament_keeps_access_choice(self):
        UserVipSubscription.objects.create(
            user=self.analyst,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(days=30),
            duration_days=30,
            source=UserVipSubscription.Source.ADMIN,
        )
        self.coupon.tournament = self.tournament
        self.coupon.save(update_fields=["tournament"])
        TournamentParticipant.objects.filter(user=self.analyst).delete()

        response = self.client.get(reverse("game:rich_prediction_create"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"]["tournament"].value(), "")
        self.assertNotContains(response, "data-rich-access-card data-tournament-hidden hidden")

    def _quick_tournament(self):
        Tournament.objects.filter(pk=self.tournament.pk).update(prediction_format=Tournament.PredictionFormat.QUICK)
        self.tournament.refresh_from_db()

    def test_ordinary_tournament_takes_coupon_published_from_panel(self):
        self._quick_tournament()

        response = self._coupon_request(autosave=False)

        self.assertEqual(response.status_code, 200, response.content)
        coupon = PredictionCoupon.objects.get(pk=response.json()["coupon_id"])
        self.assertEqual(coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(coupon.prediction_format, PredictionCoupon.PredictionFormat.QUICK)
        self.assertTrue(TournamentCoupon.objects.filter(tournament=self.tournament, coupon=coupon).exists())

    def test_ordinary_tournament_rule_violation_keeps_the_draft(self):
        self._quick_tournament()
        Tournament.objects.filter(pk=self.tournament.pk).update(min_coefficient=Decimal("2.00"))

        response = self._coupon_request(autosave=False)

        self.assertEqual(response.status_code, 400)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertFalse(TournamentCoupon.objects.exists())
        self.analyst.coin_wallet.refresh_from_db()
        self.assertEqual(self.analyst.coin_wallet.balance, 1000)

    def test_ordinary_tournament_prediction_from_editor_needs_no_text(self):
        self._quick_tournament()

        response = self._publish(headline="", description="")

        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        self.assertTrue(TournamentCoupon.objects.filter(tournament=self.tournament, coupon=self.coupon).exists())
