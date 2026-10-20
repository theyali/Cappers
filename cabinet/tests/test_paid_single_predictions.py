from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.forms import AnalystPaidPlanSettingsForm, AnalystProfileForm
from cabinet.models import AnalystPaidSubscription, PaidPredictionPurchase, User
from cabinet.paid_prediction_purchases import single_coupon_sale_blocker
from cabinet.paid_predictions import (
    accessible_paid_coupon_ids, profile_paid_predictions_enabled,
    user_can_view_paid_coupon, user_can_view_paid_predictions,
)
from cabinet.services.profile_coupon_feed import build_coupon_feed_context
from game.models import Match, Prediction, PredictionCoupon


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}, CELERY_TASK_ALWAYS_EAGER=True, STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class SingleCouponAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username="single-author", role=User.Role.ANALYST)
        cls.reader = User.objects.create_user(username="single-reader")
        cls.match = Match.objects.create(external_id=7834221, sync_scope="prematch", starts_at=timezone.now() + timedelta(days=1))
        cls.coupons = []
        for number in range(2):
            coupon = PredictionCoupon.objects.create(
                author=cls.author, total_stake=500, audience="paid", published_status="published",
                single_purchase_enabled=True, single_purchase_price=Decimal("100"),
                description=f"Секретный разбор {number}",
            )
            Prediction.objects.create(coupon=coupon, match=cls.match, market="winner", selection="Секретный исход", coefficient=2, stake=500)
            cls.coupons.append(coupon)

    def purchase(self, **overrides):
        terms = dict(buyer=self.reader, analyst=self.author, coupon=self.coupons[0],
                     status="paid", price=Decimal("100"), platform_fee_percent=Decimal("10"),
                     platform_fee_amount=Decimal("10"), capper_income=Decimal("90"), paid_at=timezone.now())
        terms.update(overrides)
        return PaidPredictionPurchase.objects.create(**terms)

    def test_purchase_opens_only_one_coupon_not_authors_subscription(self):
        self.purchase()
        self.assertTrue(user_can_view_paid_coupon(self.reader, self.coupons[0]))
        self.assertFalse(user_can_view_paid_coupon(self.reader, self.coupons[1]))
        self.assertFalse(user_can_view_paid_predictions(self.reader, self.author))
        self.assertFalse(user_can_view_paid_coupon(AnonymousUser(), self.coupons[0]))
        self.assertTrue(user_can_view_paid_coupon(self.author, self.coupons[0]))

    def test_refund_removes_purchase_right_but_keeps_subscription_right(self):
        self.purchase(status="refunded", refunded_at=timezone.now())
        self.assertFalse(user_can_view_paid_coupon(self.reader, self.coupons[0]))
        AnalystPaidSubscription.objects.create(subscriber=self.reader, analyst=self.author,
            price=100, expires_at=timezone.now() + timedelta(days=1))
        self.assertTrue(user_can_view_paid_coupon(self.reader, self.coupons[0]))

    def test_pending_failed_and_future_subscription_do_not_unlock(self):
        purchase = self.purchase(status="pending", paid_at=None)
        for status in ("pending", "failed"):
            purchase.status = status
            purchase.save()
            self.assertFalse(user_can_view_paid_coupon(self.reader, self.coupons[0]))
        AnalystPaidSubscription.objects.create(subscriber=self.reader, analyst=self.author,
            price=100, starts_at=timezone.now() + timedelta(days=1), expires_at=timezone.now() + timedelta(days=2))
        self.assertFalse(user_can_view_paid_coupon(self.reader, self.coupons[0]))

    def test_sale_disable_and_settlement_do_not_revoke_paid_access(self):
        self.purchase()
        self.coupons[0].state_status = "lose"
        self.coupons[0].save()
        self.assertTrue(user_can_view_paid_coupon(self.reader, self.coupons[0]))
        self.assertFalse(profile_paid_predictions_enabled(self.author))

    def test_page_access_is_batched(self):
        self.purchase()
        with self.assertNumQueries(2):
            self.assertEqual(accessible_paid_coupon_ids(self.reader, self.coupons * 10), {self.coupons[0].pk})

    def test_purchased_coupon_is_unlocked_in_catalog_and_profile_feed(self):
        from front.prediction_catalog_views import get_rich_predictions_queryset
        self.purchase()
        self.client.force_login(self.reader)
        response = self.client.get(reverse("front:prediction_detail", args=[self.coupons[0].pk]))
        self.assertContains(response, "Секретный исход")
        response = self.client.get(reverse("front:prediction_detail", args=[self.coupons[1].pk]))
        self.assertNotContains(response, "Секретный исход")
        context = build_coupon_feed_context(self.author, {}, public=True, viewer=self.reader)
        by_id = {row["id"]: row for row in context["coupon_feed_items"]}
        self.assertFalse(by_id[self.coupons[0].pk]["is_paid_locked"])
        self.assertTrue(by_id[self.coupons[1].pk]["is_paid_locked"])
        PredictionCoupon.objects.filter(pk__in=[c.pk for c in self.coupons]).update(prediction_format="rich")
        self.assertEqual(set(get_rich_predictions_queryset(self.reader).values_list("pk", flat=True)), {self.coupons[0].pk})

    def test_history_protects_coupon_and_users_from_deletion(self):
        self.purchase()
        for obj in (self.coupons[0], self.author, self.reader):
            with self.assertRaises(ProtectedError):
                obj.delete()

    def test_database_rejects_duplicate_and_inconsistent_paid_purchase(self):
        self.purchase()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.purchase()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.purchase(coupon=self.coupons[1], capper_income=Decimal("100"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.purchase(coupon=self.coupons[1], paid_at=None)

    @override_settings(SINGLE_COUPON_SALES_ENABLED=True)
    def test_sale_closes_at_start_of_any_express_position_and_unknown_time(self):
        profile = self.author.analyst_profile
        profile.paid_predictions_enabled = profile.single_coupon_sales_enabled = True
        profile.single_coupon_price = Decimal("100")
        profile.save()
        self.assertEqual(single_coupon_sale_blocker(self.coupons[0]), "")
        second = Match.objects.create(external_id=7834222, sync_scope="prematch", starts_at=timezone.now() - timedelta(seconds=1))
        Prediction.objects.create(coupon=self.coupons[0], match=second, market="winner", selection="home", coefficient=2, stake=500)
        self.assertTrue(single_coupon_sale_blocker(self.coupons[0]))
        second.starts_at = None
        second.save()
        self.assertTrue(single_coupon_sale_blocker(self.coupons[0]))

    @override_settings(SINGLE_COUPON_SALES_ENABLED=True)
    def test_old_coupon_explains_missing_price_and_started_match(self):
        profile = self.author.analyst_profile
        profile.paid_predictions_enabled = profile.single_coupon_sales_enabled = True
        profile.single_coupon_price = Decimal("100")
        profile.save()
        coupon = self.coupons[0]
        coupon.single_purchase_enabled = False
        coupon.single_purchase_price = None
        self.assertIn("Цена применяется к новым купонам", single_coupon_sale_blocker(coupon))
        self.match.starts_at = timezone.now() - timedelta(minutes=1)
        self.match.save(update_fields=["starts_at"])
        self.assertEqual(single_coupon_sale_blocker(coupon), "Матч начался, покупка недоступна.")

    @override_settings(SINGLE_COUPON_SALES_ENABLED=False)
    def test_rollout_is_disabled_by_default_and_old_coupons_stay_disabled(self):
        self.assertTrue(single_coupon_sale_blocker(self.coupons[0]))
        old = PredictionCoupon.objects.create(author=self.author, total_stake=1, audience="paid", published_status="published")
        self.assertFalse(old.single_purchase_enabled)
        self.assertIsNone(old.single_purchase_price)

    def test_single_only_author_and_form_do_not_need_subscription_tariffs(self):
        profile = self.author.analyst_profile
        profile.paid_predictions_enabled = profile.single_coupon_sales_enabled = True
        profile.single_coupon_price = Decimal("100")
        profile.save()
        self.assertTrue(profile_paid_predictions_enabled(self.author))
        form = AnalystPaidPlanSettingsForm({}, analyst=self.author)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.validate_sales_options(paid_enabled=True, single_enabled=True, single_price=Decimal("100")))
        form.save(self.author)
        profile.refresh_from_db()
        self.assertEqual(profile.single_coupon_price, Decimal("100"))
        self.assertEqual(profile.paid_predictions_price, 0)
        form = AnalystPaidPlanSettingsForm({}, analyst=self.author)
        self.assertTrue(form.is_valid())
        self.assertFalse(form.validate_sales_options(paid_enabled=True, single_enabled=False, single_price=None))

    def test_enabled_single_price_is_required_positive_and_has_two_decimals(self):
        for price in ("", "0", "-1", "10.001"):
            form = AnalystProfileForm({"single_coupon_sales_enabled": "on", "single_coupon_price": price}, instance=self.author.analyst_profile)
            self.assertFalse(form.is_valid())
            self.assertIn("single_coupon_price", form.errors)
