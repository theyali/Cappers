from datetime import timedelta
from decimal import Decimal
import re

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystPaidSubscription, User
from game.models import Match, Prediction, PredictionCoupon


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class CouponFeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username="feed-author", role=User.Role.ANALYST)
        cls.other = User.objects.create_user(username="feed-other", role=User.Role.ANALYST)
        cls.match = Match.objects.create(external_id=991775, sync_scope=Match.SyncScope.PREMATCH)
        cls.wins = []
        for number in range(16):
            cls.wins.append(cls.coupon(cls.author, "win", number + 1))
        cls.loss = cls.coupon(cls.author, "lose", 100)
        cls.paid = cls.coupon(cls.author, "win", 101, audience="paid")
        cls.paid.headline = "СЕКРЕТНЫЙ ЗАГОЛОВОК"
        cls.paid.description = "СЕКРЕТНОЕ ОПИСАНИЕ"
        cls.paid.possible_payout = Decimal("374.71")
        cls.paid.save(update_fields=["headline", "description", "possible_payout"])
        cls.paid.predictions.update(selection="СЕКРЕТНЫЙ ИСХОД", coefficient=Decimal("3.71"))
        cls.draft = cls.coupon(cls.author, "win", 102, published_status="draft")
        cls.foreign = cls.coupon(cls.other, "win", 103)

    @classmethod
    def coupon(cls, author, state, stake, **kwargs):
        defaults = {"published_status": "published", "audience": "free"}
        defaults.update(kwargs)
        coupon = PredictionCoupon.objects.create(
            author=author, state_status=state, total_stake=Decimal(stake),
            possible_payout=Decimal(stake * 2), **defaults,
        )
        Prediction.objects.create(coupon=coupon, match=cls.match, market="winner", selection="Хозяева",
                                  coefficient=Decimal("2"), stake=Decimal(stake))
        return coupon

    def public(self, **params):
        return self.client.get(reverse("front:expert_coupons", args=[self.author.username]), params)

    def ids(self, payload):
        return [int(value) for value in re.findall(r'data-coupon-id="(\d+)"', payload["desktop_html"])]

    def test_public_pages_filter_before_pagination_and_sort_entire_result(self):
        first = self.public(state="win", sort="stake", direction="asc").json()
        second = self.public(state="win", sort="stake", direction="asc", offset=first["next_offset"]).json()
        self.assertEqual(first["total"], 17)
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertEqual(second["next_offset"], 17)
        self.assertEqual(self.ids(first) + self.ids(second), [coupon.pk for coupon in self.wins] + [self.paid.pk])
        descending = self.public(state="win", sort="stake", direction="desc").json()
        self.assertEqual(self.ids(descending), [self.paid.pk] + [coupon.pk for coupon in reversed(self.wins)][:11])

    def test_public_shows_locked_paid_card_without_draft_or_another_author(self):
        payload = self.public(sort="stake", direction="desc").json()
        ids = self.ids(payload)
        self.assertEqual(payload["total"], 18)
        for coupon in [self.draft, self.foreign]:
            self.assertNotIn(coupon.pk, ids)
        self.assertEqual(ids[0], self.paid.pk)
        for html in (payload["html"], payload["desktop_html"]):
            self.assertIn("profile-coupon-locked", html)
            self.assertIn("real_coin.png", html)
            self.assertIn("paid-prediction-locked-body", html)
            self.assertNotIn("СЕКРЕТНЫЙ", html)
            self.assertNotIn(">3,71<", html)
            self.assertNotIn('data-sort-stake="101', html)

    def test_private_feed_requires_author_login_and_includes_own_paid_coupons(self):
        url = reverse("cabinet:profile_mobile_coupons")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.author)
        payload = self.client.get(url, {"state": "win", "sort": "stake", "direction": "desc"}).json()
        self.assertEqual(payload["total"], 17)
        self.assertEqual(self.ids(payload)[0], self.paid.pk)
        self.assertNotIn(self.draft.pk, self.ids(payload))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).json()["total"], 1)

    def test_author_and_active_subscriber_see_paid_card_without_lock(self):
        viewer = User.objects.create_user(username="feed-subscriber")
        AnalystPaidSubscription.objects.create(
            subscriber=viewer, analyst=self.author, price=Decimal("299"),
            expires_at=timezone.now() + timedelta(days=1),
        )
        for user in (self.author, viewer):
            self.client.force_login(user)
            payload = self.public(sort="stake", direction="desc").json()
            for html in (payload["html"], payload["desktop_html"]):
                self.assertNotIn("profile-coupon-locked", html)
                self.assertIn("СЕКРЕТНЫЙ ИСХОД", html)
                self.assertIn("real_coin.png", html)
                self.assertIn("3,71", html)
        self.client.force_login(self.author)
        payload = self.client.get(reverse("cabinet:profile_mobile_coupons"), {"sort": "stake"}).json()
        self.assertIn("СЕКРЕТНЫЙ ИСХОД", payload["desktop_html"])
        self.assertIn("real_coin.png", payload["desktop_html"])

    def test_expired_subscription_and_ordinary_follow_do_not_unlock_paid_card(self):
        from cabinet.models import AnalystFollow
        viewer = User.objects.create_user(username="feed-expired")
        AnalystFollow.objects.create(follower=viewer, analyst=self.author)
        AnalystPaidSubscription.objects.create(
            subscriber=viewer, analyst=self.author, price=Decimal("299"),
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.client.force_login(viewer)
        payload = self.public(sort="stake").json()
        self.assertIn("profile-coupon-locked", payload["desktop_html"])
        self.assertNotIn("СЕКРЕТНЫЙ", payload["desktop_html"])

    @override_settings(SINGLE_COUPON_SALES_ENABLED=False)
    def test_pending_paid_card_offers_subscription_and_completed_card_closes_purchase(self):
        profile = self.author.analyst_profile
        profile.paid_predictions_enabled = True
        profile.paid_predictions_price = Decimal("299")
        profile.save()
        payload = self.public(sort="stake").json()
        self.assertIn("Покупка закрыта", payload["desktop_html"])
        self.paid.state_status = PredictionCoupon.StateStatus.PENDING
        self.paid.save(update_fields=["state_status"])
        payload = self.public(state="pending").json()
        self.assertIn("Выбрать подписку", payload["desktop_html"])
        self.assertIn("Разовые покупки пока недоступны.", payload["desktop_html"])
        self.assertNotIn("СЕКРЕТНЫЙ", payload["desktop_html"])

    def test_locked_ajax_cards_keep_offers_in_inert_template_and_have_one_purchase_button(self):
        profile = self.author.analyst_profile
        profile.paid_predictions_enabled = True
        profile.paid_predictions_price = Decimal("299")
        profile.save()
        self.paid.state_status = PredictionCoupon.StateStatus.PENDING
        self.paid.save(update_fields=["state_status"])
        payload = self.public(state="pending").json()
        for key in ("html", "desktop_html"):
            html = payload[key]
            visible, template = html.split("<template data-expert-public-modal-content>", 1)
            self.assertEqual(visible.count("<button"), 1)
            self.assertIn('data-expert-public-modal-open="coupon-access"', visible)
            self.assertIn('aria-controls="profile-coupon-access-modal"', visible)
            self.assertIn("Приобрести", visible)
            self.assertNotIn("paid-prediction-locked-body", visible)
            self.assertNotIn("paid-prediction-offer", visible)
            self.assertNotIn("<a ", visible)
            self.assertIn("Этот прогноз платный", template)
            self.assertIn("Выбрать подписку", template)
            self.assertIn(f"купона #{self.paid.pk}", template)
            self.assertNotIn("СЕКРЕТНЫЙ", template)

    def test_profile_has_single_shared_access_dialog_for_desktop_and_mobile_cards(self):
        self.author.prediction_coupons.exclude(pk=self.paid.pk).delete()
        response = self.client.get(reverse("front:expert_profile", args=[self.author.username]))
        self.assertContains(response, 'id="profile-coupon-access-modal"', count=1)
        self.assertContains(response, 'data-expert-public-modal-slot', count=1)
        self.assertContains(response, 'aria-label="Доступ к платному прогнозу"')
        self.assertContains(response, 'data-expert-public-modal-content', count=2)

    def test_public_profile_renders_feed_when_author_has_only_paid_predictions(self):
        self.author.prediction_coupons.exclude(pk=self.paid.pk).delete()
        response = self.client.get(reverse("front:expert_profile", args=[self.author.username]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-profile-coupon-feed")
        self.assertContains(response, "profile-coupon-locked")
        self.assertContains(response, "paid-prediction-locked-body")
        self.assertNotContains(response, "СЕКРЕТНЫЙ")

    def test_empty_invalid_parameters_and_private_profile(self):
        empty = self.public(state="pending").json()
        self.assertEqual(empty["total"], 0)
        self.assertFalse(empty["has_more"])
        self.assertEqual(empty["desktop_html"].strip(), "")
        invalid = self.public(sort="unknown", direction="unknown", state="unknown", offset="invalid").json()
        default = self.public().json()
        self.assertEqual(self.ids(invalid), self.ids(default))
        self.author.analyst_profile.is_public = False
        self.author.analyst_profile.save(update_fields=["is_public"])
        self.assertEqual(self.public().status_code, 404)
