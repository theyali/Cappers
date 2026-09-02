from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from front.models import PredictionFavorite, PredictionLike
from game.models import Match, Prediction, PredictionCoupon

from .models import AnalystFollow, User


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class CapperDashboardTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="dashboard-analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(
            username="dashboard-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.now = timezone.now()

    def _match(self, external_id: int, *, scope=Match.SyncScope.LIVE, score="1-1"):
        return Match.objects.create(
            external_id=external_id,
            sync_scope=scope,
            starts_at=self.now,
            score=score,
        )

    def _coupon(self, *, state, stake, payout, confidence=70, settled=True):
        return PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=state,
            total_stake=Decimal(stake),
            possible_payout=Decimal(payout),
            confidence=confidence,
            settled_at=self.now if settled else None,
            published_at=self.now,
        )

    def test_old_dashboard_url_redirects_to_profile_for_every_role(self):
        for user in (self.reader, self.analyst):
            self.client.force_login(user)
            response = self.client.get(reverse("cabinet:dashboard"))
            self.assertRedirects(response, reverse("cabinet:profile"))

    def test_profile_tab_shows_old_dashboard_content(self):
        win_coupon = self._coupon(
            state=PredictionCoupon.StateStatus.WIN,
            stake="100",
            payout="180",
            confidence=80,
        )
        lose_coupon = self._coupon(
            state=PredictionCoupon.StateStatus.LOSE,
            stake="50",
            payout="90",
            confidence=65,
        )
        pending_coupon = self._coupon(
            state=PredictionCoupon.StateStatus.PENDING,
            stake="40",
            payout="72",
            confidence=74,
            settled=False,
        )

        Prediction.objects.create(
            coupon=win_coupon,
            match=self._match(91001),
            market="total",
            selection="ТБ 2.5",
            coefficient=Decimal("1.80"),
            stake=Decimal("100"),
            state_status=Prediction.StateStatus.WIN,
        )
        Prediction.objects.create(
            coupon=lose_coupon,
            match=self._match(91002),
            market="winner",
            selection="Ничья",
            coefficient=Decimal("1.90"),
            stake=Decimal("50"),
            state_status=Prediction.StateStatus.LOSE,
        )
        Prediction.objects.create(
            coupon=pending_coupon,
            match=self._match(91003),
            market="both_score",
            selection="Обе забьют: да",
            coefficient=Decimal("1.70"),
            stake=Decimal("40"),
            state_status="",
        )

        AnalystFollow.objects.create(follower=self.reader, analyst=self.analyst)
        PredictionLike.objects.create(user=self.reader, prediction=win_coupon)
        PredictionFavorite.objects.create(user=self.reader, prediction=win_coupon)

        self.client.force_login(self.analyst)
        response = self.client.get(reverse("cabinet:profile"), {"tab": "profile"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "profile")
        self.assertEqual(response.context["today_stats"]["active"], 3)
        self.assertEqual(response.context["today_stats"]["wins"], 1)
        self.assertEqual(response.context["today_stats"]["losses"], 1)
        self.assertEqual(response.context["today_stats"]["pending"], 1)
        self.assertEqual(response.context["today_stats"]["live"], 3)
        self.assertEqual(response.context["new_followers_count"], 1)
        self.assertEqual(len(response.context["latest_reactions"]), 2)
        self.assertEqual(len(response.context["live_predictions"]), 3)
        self.assertEqual(response.context["roi_today_display"], "+20.0%")
        self.assertContains(response, "Текущие live-прогнозы")
        self.assertContains(response, "Последние реакции")
        self.assertContains(response, "Настройки")
        self.assertContains(response, "prediction-table-row", count=3)
        self.assertNotContains(response, 'class="capper-live-card"')

    def test_recent_reaction_uses_account_avatar_and_two_letter_initials(self):
        self.reader.first_name = "Aleksey"
        self.reader.last_name = "Sorokin"
        self.reader.avatar = "users/avatars/reaction-reader.jpg"
        self.reader.save(update_fields=["first_name", "last_name", "avatar"])

        coupon = self._coupon(
            state=PredictionCoupon.StateStatus.PENDING,
            stake="100",
            payout="180",
            settled=False,
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self._match(92001),
            market="winner",
            selection="П1",
            coefficient=Decimal("1.80"),
            stake=Decimal("100"),
            state_status="",
        )
        PredictionLike.objects.create(user=self.reader, prediction=coupon)

        self.client.force_login(self.analyst)
        response = self.client.get(reverse("cabinet:profile"), {"tab": "profile"})

        reaction = response.context["latest_reactions"][0]
        self.assertEqual(reaction["initial"], "AS")
        self.assertTrue(reaction["avatar_url"].endswith("/users/avatars/reaction-reader.jpg"))
        self.assertContains(response, 'width="38" height="38"')

        self.reader.avatar = None
        self.reader.save(update_fields=["avatar"])
        response = self.client.get(reverse("cabinet:profile"), {"tab": "profile"})
        reaction = response.context["latest_reactions"][0]

        self.assertEqual(reaction["avatar_url"], "")
        self.assertEqual(reaction["initial"], "AS")
        self.assertContains(response, "AS")

    def test_profile_dashboard_shows_confidence_calibration(self):
        for index in range(5):
            self._coupon(
                state=(
                    PredictionCoupon.StateStatus.WIN
                    if index < 3
                    else PredictionCoupon.StateStatus.LOSE
                ),
                stake="100",
                payout="180",
                confidence=80,
            )
        self._coupon(
            state=PredictionCoupon.StateStatus.REFUND,
            stake="100",
            payout="100",
            confidence=80,
        )
        self._coupon(
            state=PredictionCoupon.StateStatus.PENDING,
            stake="100",
            payout="200",
            confidence=80,
            settled=False,
        )

        self.client.force_login(self.analyst)
        response = self.client.get(reverse("cabinet:profile"), {"tab": "profile"})

        calibration = response.context["dashboard_confidence_calibration"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calibration["total"], 5)
        self.assertEqual(calibration["refunds"], 1)
        self.assertEqual(calibration["average_abs_error"], 20.0)
        self.assertEqual(calibration["accuracy_tone"], "danger")
        self.assertEqual(calibration["accuracy_label"], "сильное завышение")
        self.assertEqual(
            response.context["dashboard_confidence_recommendation"]["title"],
            "Уверенность завышается",
        )
        self.assertContains(response, "Моя калибровка")
        self.assertContains(response, "Средняя ошибка")
        self.assertContains(response, "20,0 п.п.")
        self.assertContains(response, "завышает на 20,0 п.п.")
        self.assertContains(response, "сильное завышение")
        self.assertContains(response, "is-danger")
        self.assertContains(response, "80-89%")
        self.assertContains(response, "60,0%")

    def test_settings_tab_contains_account_form(self):
        self.client.force_login(self.analyst)
        response = self.client.get(reverse("cabinet:profile"), {"tab": "settings"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "settings")
        self.assertContains(response, "Личные данные")
        self.assertContains(response, "Сохранить изменения")
        self.assertContains(response, 'data-profile-tab-panel="settings"')
