import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User, UserVipSubscription
from game.models import Match, MatchOdds, Prediction, PredictionCoupon, PredictionCoverImage, Sport
from game.services.coupon_validation import CouponMatchVerificationError
from game.services.prediction_editor import update_rich_prediction
from game.services.settlement import settle_coupon
from wallets.models import CoinTransaction


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class RichPredictionPublishTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="rich-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        UserVipSubscription.objects.create(
            user=self.analyst,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(days=30),
            duration_days=30,
            source=UserVipSubscription.Source.ADMIN,
        )
        self.match = Match.objects.create(
            external_id=773001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=2),
            raw_data={
                "teams": {
                    "home": {"name": {"ru": "Арсенал"}},
                    "away": {"name": {"ru": "Челси"}},
                },
            },
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
        self.prediction = Prediction.objects.create(
            coupon=self.coupon,
            match=self.match,
            market="winner",
            selection="Арсенал",
            coefficient=Decimal("1.85"),
            stake=Decimal("500"),
        )
        self.client.force_login(self.analyst)

    def test_gallery_cover_from_another_sport_can_be_selected_and_saved(self):
        self.coupon.prediction_format = PredictionCoupon.PredictionFormat.RICH
        self.coupon.save(update_fields=["prediction_format"])
        football = Sport.objects.create(code="football", name="Football")
        tennis = Sport.objects.create(code="tennis", name="Tennis")
        self.match.sport = football
        self.match.save(update_fields=["sport"])
        cover = PredictionCoverImage.objects.create(sport=tennis, image="prediction_covers/tennis.webp")
        url = reverse("game:rich_prediction_edit", kwargs={"coupon_id": self.coupon.pk})
        gallery = self.client.get(url)
        self.assertIn(cover, gallery.context["available_covers"])
        response = self._edit(cover_image=str(cover.pk), published_status="draft")
        self.assertEqual(response.status_code, 302, response.context["form"].errors if response.status_code == 200 else "")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.cover_image_id, cover.pk)

    def test_inactive_and_slider_covers_remain_unavailable(self):
        sport = Sport.objects.create(code="football", name="Football")
        for overrides in ({"is_active": False}, {"placement": "home_slider"}):
            cover = PredictionCoverImage.objects.create(
                sport=sport, image="prediction_covers/hidden.webp", **overrides,
            )
            response = self._edit(cover_image=str(cover.pk), published_status="draft")
            self.assertEqual(response.status_code, 200)
            self.assertIn("cover_image", response.context["form"].errors)
            self.assertNotIn(cover, response.context["available_covers"])
        self.coupon.refresh_from_db()
        self.assertIsNone(self.coupon.cover_image_id)

    def _add_coupon_position(self):
        match = Match.objects.create(
            external_id=773002, sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=2),
        )
        return Prediction.objects.create(
            coupon=self.coupon, match=match, market="winner", selection="Хозяева",
            coefficient=Decimal("2.50"), stake=self.coupon.total_stake,
        )

    def _remove_position(self, prediction=None, coupon=None):
        return self.client.post(reverse("game:rich_prediction_remove", kwargs={
            "coupon_id": (coupon or self.coupon).pk,
            "prediction_id": (prediction or self.prediction).pk,
        }))

    def test_remove_position_persists_and_recalculates_draft_without_publishing(self):
        remaining = self._add_coupon_position()
        response = self._remove_position()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["positions_count"], 1)
        self.assertEqual(Decimal(response.json()["total_coefficient"]), Decimal("2.50"))
        self.assertFalse(Prediction.objects.filter(pk=self.prediction.pk).exists())
        self.assertTrue(Prediction.objects.filter(pk=remaining.pk).exists())
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.possible_payout, Decimal("1250"))
        self.assertEqual(self.coupon.coupon_type, PredictionCoupon.CouponType.SINGLE)
        self.assertEqual(self.coupon.prediction_format, PredictionCoupon.PredictionFormat.QUICK)
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertFalse(self._stake_transactions().exists())
        # A retried request cannot delete another position.
        self.assertEqual(self._remove_position().status_code, 200)
        self.assertTrue(Prediction.objects.filter(pk=remaining.pk).exists())

    def test_remove_position_keeps_last_position(self):
        response = self._remove_position()
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Prediction.objects.filter(pk=self.prediction.pk).exists())

    def test_remove_position_rejects_published_and_other_authors_coupons(self):
        self._add_coupon_position()
        self.coupon.published_status = PredictionCoupon.PublishedStatus.PUBLISHED
        self.coupon.save(update_fields=["published_status"])
        self.assertEqual(self._remove_position().status_code, 400)
        self.assertTrue(Prediction.objects.filter(pk=self.prediction.pk).exists())
        stranger = User.objects.create_user(username="remove-stranger", role=User.Role.ANALYST)
        self.client.force_login(stranger)
        self.assertEqual(self._remove_position().status_code, 404)
        self.assertTrue(Prediction.objects.filter(pk=self.prediction.pk).exists())

    def test_remove_position_works_for_rich_draft_and_rejects_non_vip(self):
        self._add_coupon_position()
        self.coupon.prediction_format = PredictionCoupon.PredictionFormat.RICH
        self.coupon.save(update_fields=["prediction_format"])
        self.assertEqual(self._remove_position().status_code, 200)
        self.analyst.vip_subscriptions.all().delete()
        self.assertEqual(self._remove_position(prediction=self.coupon.predictions.get()).status_code, 403)
        self.assertEqual(self.coupon.predictions.count(), 1)

    def test_paid_forecast_requires_title_and_description_from_300_characters(self):
        for description in ("", " " * 300, "я" * 299):
            with self.subTest(description_length=len(description)):
                response = self._publish(is_paid="on", headline="  ", description=description)
                self.assertEqual(response.status_code, 200)
                self.assertIn("headline", response.context["form"].errors)
                self.assertIn("description", response.context["form"].errors)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertFalse(self._stake_transactions().exists())

    def _enable_paid_predictions(self):
        profile = self.analyst.analyst_profile
        profile.paid_predictions_enabled = True
        profile.paid_predictions_price = Decimal("299")
        profile.save(update_fields=["paid_predictions_enabled", "paid_predictions_price"])

    def test_paid_draft_with_title_and_300_characters_saves(self):
        self._enable_paid_predictions()
        response = self._publish(is_paid="on", headline="Платный разбор", description="я" * 300,
                                 published_status="draft")
        self.assertEqual(response.status_code, 302)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.audience, PredictionCoupon.Audience.PAID)
        self.assertEqual(self.coupon.headline, "Платный разбор")
        self.assertEqual(self.coupon.description, "я" * 300)

    def test_service_checks_paid_content_when_form_is_bypassed(self):
        self._enable_paid_predictions()
        self.coupon.prediction_format = PredictionCoupon.PredictionFormat.RICH
        self.coupon.save(update_fields=["prediction_format"])
        with self.assertRaises(ValidationError) as caught:
            update_rich_prediction(self.analyst, self.coupon, {
                "is_paid": True, "headline": " ", "description": "я" * 299,
                "published_status": "draft",
            }, {})
        self.assertIn("headline", caught.exception.message_dict)
        self.assertIn("description", caught.exception.message_dict)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.audience, PredictionCoupon.Audience.FREE)

    def test_free_forecast_keeps_optional_title_and_description(self):
        response = self._publish(headline="", description="")
        self.assertEqual(response.status_code, 302)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(self.coupon.audience, PredictionCoupon.Audience.FREE)

    def test_started_draft_match_is_marked_before_publish(self):
        self.match.starts_at = timezone.now() - timedelta(minutes=1)
        self.match.save(update_fields=["starts_at"])
        response = self.client.get(reverse("game:rich_prediction_create"))
        self.assertTrue(response.context["coupon_timing_blocked"])
        self.assertTrue(response.context["predictions"][0].editor_prediction_closed)
        self.assertContains(response, 'class="rich-prediction-coupon-item is-timing-locked"')
        self.assertContains(response, "Удалите отмеченные красным игры перед публикацией")
        self.assertContains(response, 'data-coupon-match-id="%s"' % self.match.pk)
        self.assertEqual(response.content.decode().count("data-rich-publish disabled"), 3)

    def test_upcoming_match_remains_available_even_when_starting_soon(self):
        self.match.starts_at = timezone.now() + timedelta(minutes=5)
        self.match.save(update_fields=["starts_at"])
        response = self.client.get(reverse("game:rich_prediction_create"))
        self.assertFalse(response.context["coupon_timing_blocked"])
        self.assertFalse(response.context["predictions"][0].editor_prediction_closed)
        self.assertTrue(response.context["rich_prediction_timing"][str(self.match.pk)]["prediction_open"])

    def test_missing_time_and_live_matches_are_marked_in_advance(self):
        for scope, starts_at in [(Match.SyncScope.LIVE, timezone.now() + timedelta(hours=1)),
                                 (Match.SyncScope.PREMATCH, None)]:
            with self.subTest(scope=scope):
                self.match.sync_scope = scope
                self.match.starts_at = starts_at
                self.match.save(update_fields=["sync_scope", "starts_at"])
                response = self.client.get(reverse("game:rich_prediction_create"))
                self.assertTrue(response.context["coupon_timing_blocked"])
                self.assertTrue(response.context["predictions"][0].editor_prediction_closed)

    def test_published_forecast_keeps_content_editing_after_kickoff(self):
        self._publish()
        self.match.starts_at = timezone.now() - timedelta(minutes=1)
        self.match.save(update_fields=["starts_at"])
        response = self.client.get(reverse("game:rich_prediction_edit", args=[self.coupon.pk]))
        self.assertFalse(response.context["coupon_timing_blocked"])
        self.assertNotContains(response, 'data-coupon-match-id="%s"' % self.match.pk)

    def test_paid_option_requires_configured_settings_and_forged_post_is_rejected(self):
        response = self.client.get(reverse("game:rich_prediction_create"))
        self.assertFalse(response.context["can_publish_paid"])
        self.assertContains(response, "В настройки → настроить платные прогнозы")
        self.assertContains(response, 'target="_blank"')
        response = self._publish(is_paid="on", description="я" * 300)
        self.assertEqual(response.status_code, 200)
        self.assertIn("is_paid", response.context["form"].errors)
        self.assertFalse(self._stake_transactions().exists())
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.audience, PredictionCoupon.Audience.FREE)
        self._enable_paid_predictions()
        response = self.client.get(reverse("game:rich_prediction_create"))
        self.assertTrue(response.context["can_publish_paid"])
        self.assertTrue(self.client.get(reverse("game:coupon_draft_state")).json()["paid_available"])

    def test_paid_service_requires_settings_even_if_form_is_bypassed(self):
        self.coupon.prediction_format = PredictionCoupon.PredictionFormat.RICH
        self.coupon.save(update_fields=["prediction_format"])
        with self.assertRaises(ValidationError) as caught:
            update_rich_prediction(self.analyst, self.coupon, {
                "is_paid": True, "headline": "Название", "description": "я" * 300,
                "published_status": "draft",
            }, {})
        self.assertIn("is_paid", caught.exception.message_dict)

    def test_published_draft_cannot_be_resurrected_by_stale_autosave(self):
        self.coupon.refresh_from_db()
        previous_revision = self.coupon.updated_at.isoformat()
        previous_id = self.coupon.pk
        response = self._publish()
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.client.get(reverse("game:coupon_draft_state")).json()["draft"])
        payload = {"autosave": True, "coupon_id": previous_id, "base_revision": previous_revision,
                   "stake": "500", "confidence": 70, "items": [{
                       "match_id": self.match.pk, "market": "winner", "selection": "Арсенал", "coefficient": "1.85",
                   }]}
        response = self.client.post(reverse("game:create_coupon"), json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["draft_conflict"])
        self.assertIsNone(response.json()["draft"])
        self.assertEqual(PredictionCoupon.objects.filter(author=self.analyst).count(), 1)

    def test_removal_in_editor_changes_shared_version_and_rejects_stale_basket(self):
        self._add_coupon_position()
        original = self.client.get(reverse("game:coupon_draft_state")).json()["draft"]
        response = self._remove_position()
        self.assertEqual(response.status_code, 200)
        state = self.client.get(reverse("game:coupon_draft_state"), {"editor": "1"}).json()
        self.assertEqual(len(state["draft"]["items"]), 1)
        self.assertNotEqual(original["revision"], state["draft"]["revision"])
        self.assertNotIn('data-prediction-id="%s"' % self.prediction.pk, state["editor_html"])
        stale = {"autosave": True, "coupon_id": self.coupon.pk, "base_revision": original["revision"],
                 "stake": "500", "confidence": 70, "items": [{
                     "match_id": self.match.pk, "market": "winner", "selection": "Арсенал", "coefficient": "1.85",
                 }]}
        response = self.client.post(reverse("game:create_coupon"), json.dumps(stale), content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.coupon.predictions.count(), 1)
        self.assertFalse(self.coupon.predictions.filter(match=self.match).exists())

    def test_removal_in_games_is_reflected_by_editor_state_and_new_page(self):
        second = self._add_coupon_position()
        original = self.client.get(reverse("game:coupon_draft_state")).json()["draft"]
        payload = {"autosave": True, "coupon_id": self.coupon.pk, "base_revision": original["revision"],
                   "stake": "500", "confidence": 70, "items": [{
                       "match_id": self.match.pk, "market": "winner", "selection": "Арсенал", "coefficient": "1.85",
                   }]}
        response = self.client.post(reverse("game:create_coupon"), json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        state = self.client.get(reverse("game:coupon_draft_state"), {"editor": "1"}).json()
        self.assertEqual([item["matchId"] for item in state["draft"]["items"]], [str(self.match.pk)])
        self.assertNotIn('data-coupon-match-id="%s"' % second.match_id, state["editor_html"])
        page = self.client.get(reverse("game:rich_prediction_create"))
        self.assertEqual(len(page.context["predictions"]), 1)
        payload.update({"base_revision": state["draft"]["revision"], "items": []})
        response = self.client.post(reverse("game:create_coupon"), json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.get(reverse("game:coupon_draft_state")).json()["draft"])

    def test_stale_empty_save_cannot_clear_a_newer_draft(self):
        second = self._add_coupon_position()
        original = self.client.get(reverse("game:coupon_draft_state")).json()["draft"]
        self.assertEqual(self._remove_position(prediction=second).status_code, 200)
        response = self.client.post(reverse("game:create_coupon"), json.dumps({
            "autosave": True, "coupon_id": self.coupon.pk,
            "base_revision": original["revision"], "items": [],
        }), content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(self.coupon.predictions.filter(pk=self.prediction.pk).exists())

    def test_stale_rich_form_must_review_the_new_coupon_before_publishing(self):
        second = self._add_coupon_position()
        original = self.client.get(reverse("game:coupon_draft_state")).json()["draft"]
        self.assertEqual(self._remove_position(prediction=second).status_code, 200)
        response = self._publish(draft_revision=original["revision"])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Состав купона изменён в другой вкладке")
        self.assertFalse(self._stake_transactions().exists())
        # The re-rendered form presents the new version so the user can retry.
        current = self.client.get(reverse("game:coupon_draft_state")).json()["draft"]
        self.assertContains(response, 'value="%s"' % current["revision"])

    def test_draft_state_is_private_and_empty_editor_keeps_shared_listener(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("game:coupon_draft_state")).status_code, 302)
        stranger = User.objects.create_user(username="draft-stranger", role=User.Role.ANALYST)
        self.client.force_login(stranger)
        state = self.client.get(reverse("game:coupon_draft_state")).json()
        self.assertIsNone(state["draft"])
        self.client.force_login(self.analyst)
        self._publish()
        page = self.client.get(reverse("game:rich_prediction_create"))
        self.assertContains(page, "data-shared-coupon-page")
        self.assertContains(page, "front/js/prediction-reactions.js")
        self.assertContains(page, 'id="coupon-draft-data"')

    def _form(self, **overrides):
        data = {
            "total_stake": "500",
            "confidence": "70",
            "headline": "Арсенал дома сильнее",
            "published_status": PredictionCoupon.PublishedStatus.PUBLISHED,
        }
        data.update(overrides)
        return data

    def _publish(self, **overrides):
        return self.client.post(reverse("game:rich_prediction_create"), self._form(**overrides))

    def _edit(self, **overrides):
        return self.client.post(
            reverse("game:rich_prediction_edit", kwargs={"coupon_id": self.coupon.pk}),
            self._form(**overrides),
        )

    def _stake_transactions(self):
        return CoinTransaction.objects.filter(
            user=self.analyst,
            kind=CoinTransaction.Kind.PREDICTION_STAKE,
        )

    def _balance(self):
        self.analyst.coin_wallet.refresh_from_db()
        return self.analyst.coin_wallet.balance

    def test_publish_charges_stake_once(self):
        response = self._publish()

        self.assertRedirects(
            response,
            reverse("game:rich_prediction_create"),
            fetch_redirect_response=False,
        )
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(self.coupon.prediction_format, PredictionCoupon.PredictionFormat.RICH)
        self.assertEqual(self._balance(), 500)
        self.assertEqual(list(self._stake_transactions().values_list("amount", flat=True)), [-500])

        self._edit(headline="Обновлённый заголовок")

        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.headline, "Обновлённый заголовок")
        self.assertEqual(self._balance(), 500)
        self.assertEqual(self._stake_transactions().count(), 1)

    def test_successful_publish_resets_editor_and_shows_public_link(self):
        response = self.client.post(
            reverse("game:rich_prediction_create"),
            self._form(),
            follow=True,
        )

        self.assertRedirects(response, reverse("game:rich_prediction_create"))
        self.assertContains(response, "Прогноз опубликован")
        self.assertContains(
            response,
            reverse("front:prediction_detail", kwargs={"prediction_id": self.coupon.pk}),
        )
        self.assertContains(response, "Сначала выберите матчи")
        self.assertNotContains(response, "data-rich-coupon-item")
        self.assertNotContains(response, 'value="Арсенал дома сильнее"')

    def test_publish_backfills_outcome_code_of_old_drafts(self):
        self.assertEqual(self.prediction.outcome_code, "")

        self._publish()

        self.prediction.refresh_from_db()
        self.assertEqual(self.prediction.outcome_code, "1")

    def test_publish_without_enough_coins_keeps_draft(self):
        response = self._publish(total_stake="1500")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Недостаточно коинов")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertEqual(self.coupon.prediction_format, PredictionCoupon.PredictionFormat.QUICK)
        self.assertFalse(self._stake_transactions().exists())
        self.assertEqual(self._balance(), 1000)

    def test_publish_after_kickoff_is_rejected(self):
        Match.objects.filter(pk=self.match.pk).update(starts_at=timezone.now() - timedelta(minutes=1))

        response = self._publish()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже начался или скоро начнется")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertFalse(self._stake_transactions().exists())

    def test_provider_outage_is_reported_as_form_error(self):
        with patch(
            "game.services.prediction_editor.verify_matches_for_coupon",
            side_effect=CouponMatchVerificationError("Сервис спортивных данных временно недоступен."),
        ):
            response = self._publish()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сервис спортивных данных временно недоступен.")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)

    def test_changed_line_updates_draft_and_requires_confirmation(self):
        MatchOdds.objects.filter(match=self.match).update(home_win_bet=2.05)

        response = self._publish()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Коэффициенты изменились")
        self.prediction.refresh_from_db()
        self.assertEqual(self.prediction.coefficient, Decimal("2.05"))
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertFalse(self._stake_transactions().exists())

        self._publish()

        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(self.coupon.possible_payout, Decimal("1025.00"))
        self.assertEqual(self._balance(), 500)

    def test_outcome_missing_from_line_blocks_publish(self):
        MatchOdds.objects.filter(match=self.match).update(home_win_bet=None, x_bet=3.4)

        response = self._publish()

        self.assertContains(response, "сейчас недоступен")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)

    def test_published_coupon_keeps_stake_positions_and_status(self):
        self._publish()

        page = self.client.get(reverse("game:rich_prediction_edit", kwargs={"coupon_id": self.coupon.pk}))
        self.assertContains(page, "Сохранить изменения")
        self.assertNotContains(page, "Сохранить черновик")
        self.assertNotContains(page, "data-rich-remove-prediction")

        self._edit(total_stake="100000")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.total_stake, Decimal("500.00"))

        response = self._edit(remove_prediction_ids=str(self.prediction.pk))
        self.assertContains(response, "Позиции опубликованного прогноза изменить нельзя.")
        self.assertTrue(Prediction.objects.filter(pk=self.prediction.pk).exists())

        response = self._edit(published_status=PredictionCoupon.PublishedStatus.DRAFT)
        self.assertContains(response, "нельзя вернуть в черновик")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(self._balance(), 500)

    def test_service_rejects_stake_change_after_publish(self):
        self._publish()
        self.coupon.refresh_from_db()

        with self.assertRaises(ValidationError) as caught:
            update_rich_prediction(
                self.analyst,
                self.coupon,
                {"total_stake": Decimal("100000"), "published_status": "published"},
                {},
            )

        self.assertIn("total_stake", caught.exception.message_dict)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.total_stake, Decimal("500.00"))

    def test_service_rejects_audience_change_after_publish(self):
        self._publish()
        self.coupon.refresh_from_db()

        with self.assertRaises(ValidationError) as caught:
            update_rich_prediction(
                self.analyst,
                self.coupon,
                {"is_paid": True, "published_status": "published"},
                {},
            )

        self.assertIn("is_paid", caught.exception.message_dict)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.audience, PredictionCoupon.Audience.FREE)

    def test_editor_cannot_cancel_coupon(self):
        self._publish()
        self.coupon.refresh_from_db()

        with self.assertRaises(ValidationError):
            update_rich_prediction(
                self.analyst,
                self.coupon,
                {"published_status": PredictionCoupon.PublishedStatus.CANCELED},
                {},
            )

        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)


class UnpaidCouponSettlementTests(TestCase):
    def test_missing_coins_do_not_block_settlement(self):
        analyst = User.objects.create_user(
            username="unpaid-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        match = Match.objects.create(
            external_id=773101,
            sync_scope=Match.SyncScope.FINISHED,
            starts_at=timezone.now() - timedelta(hours=3),
        )
        coupon = PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("5000"),
            possible_payout=Decimal("9250.00"),
            confidence=70,
            published_at=timezone.now() - timedelta(hours=4),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("1.85"),
            stake=Decimal("5000"),
            state_status=Prediction.StateStatus.WIN,
        )

        settle_coupon(coupon.pk)

        coupon.refresh_from_db()
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.WIN)
        self.assertIsNotNone(coupon.settled_at)
        analyst.coin_wallet.refresh_from_db()
        self.assertEqual(analyst.coin_wallet.balance, 1000)
        self.assertFalse(
            CoinTransaction.objects.filter(
                user=analyst,
                kind__in=(
                    CoinTransaction.Kind.PREDICTION_STAKE,
                    CoinTransaction.Kind.PREDICTION_PAYOUT,
                ),
            ).exists()
        )
