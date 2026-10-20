from datetime import timedelta
from decimal import Decimal
import re

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystPaidSubscription, PaidPredictionPurchase, User
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
            self.assertIn("paid-prediction-access-body", html)
            self.assertNotIn("СЕКРЕТНЫЙ", html)
            self.assertNotIn(">3,71<", html)
            self.assertNotIn('data-sort-stake="101', html)

    def test_locked_coupon_shows_lifecycle_status_on_mobile_and_desktop(self):
        for state, settled_at, label in [
            ("pending", None, "Активный"),
            ("win", None, "Завершён"),
            ("lose", None, "Завершён"),
            ("refund", None, "Завершён"),
            ("pending", timezone.now(), "Завершён"),
        ]:
            with self.subTest(state=state, settled_at=settled_at):
                PredictionCoupon.objects.filter(pk=self.paid.pk).update(state_status=state, settled_at=settled_at)
                payload = self.public(sort="stake", direction="desc").json()
                for html in (payload["html"], payload["desktop_html"]):
                    card = re.search(r'<article[^>]*profile-coupon-locked.*?</article>', html, re.S).group()
                    self.assertIn("profile-coupon-lock-status", card)
                    self.assertIn(label, card)
                    self.assertNotIn("СЕКРЕТНЫЙ", card)
                    self.assertEqual("is-completed" in card, label == "Завершён")

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

    def test_purchases_feed_filters_sorts_pages_and_preserves_buyer_access(self):
        buyer = User.objects.create_user(username="coupon-buyer")
        stranger = User.objects.create_user(username="coupon-stranger")
        coupons = []
        now = timezone.now()
        for number in range(14):
            coupon = self.coupon(self.author, "win" if number % 2 else "pending", number + 200, audience="paid")
            coupons.append(coupon)
            PaidPredictionPurchase.objects.create(
                buyer=buyer, analyst=self.author, coupon=coupon, status="paid", price=number + 50,
                platform_fee_percent=0, platform_fee_amount=0, capper_income=number + 50,
                paid_at=now + timedelta(minutes=number),
            )
        self.client.force_login(buyer)
        url = reverse("cabinet:coupon_purchases")
        response = self.client.get(url)
        self.assertContains(response, "profile-desktop-list-head")
        self.assertContains(response, "profile-desktop-sort-toolbar")
        self.assertContains(response, 'data-profile-coupon-sort="price"')
        self.assertContains(response, f"#{coupons[-1].pk}")
        self.assertContains(response, 'profile-sidebar-link is-active')

        def fetch(**params):
            return self.client.get(url, params, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()

        first = fetch(sort="price", direction="asc")
        second = fetch(sort="price", direction="asc", offset=first["next_offset"])
        self.assertEqual(first["total"], 14)
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertEqual(self.ids(first) + self.ids(second), [coupon.pk for coupon in coupons])
        self.assertNotIn("profile-coupon-locked", first["html"])
        self.assertNotIn("profile-coupon-locked", first["desktop_html"])
        self.assertEqual(self.ids(fetch(sort="date"))[0], coupons[-1].pk)
        self.assertEqual(fetch(state="win")["total"], 7)
        PaidPredictionPurchase.objects.filter(buyer=buyer, coupon=coupons[0]).update(status="refunded", refunded_at=now)
        self.assertNotIn(coupons[0].pk, self.ids(fetch(sort="price", direction="asc")))
        refunded_page = self.client.get(url, {"status": "refunded"})
        self.assertContains(refunded_page, "profile-desktop-sort-toolbar")
        self.assertContains(refunded_page, 'data-purchase-status="refunded"')
        self.assertNotContains(refunded_page, "profile-purchases-table")
        self.assertContains(refunded_page, 'data-profile-purchase-status="refunded" class="is-active"')
        refunds = fetch(status="refunded")
        self.assertEqual(refunds["total"], 1)
        self.assertEqual(self.ids(refunds), [coupons[0].pk])
        for html in (refunds["html"], refunds["desktop_html"]):
            self.assertIn("Возвращено", html)
            self.assertIn("profile-coupon-card profile-desktop-coupon", html)
            self.assertNotIn("Хозяева", html)
            self.assertNotIn('data-sort-stake=', html)
        self.assertEqual(fetch(status="refunded", state="win")["total"], 0)
        self.assertEqual(fetch(status="refunded", sort="price", direction="asc")["total"], 1)
        self.client.force_login(stranger)
        self.assertEqual(fetch()["total"], 0)
        self.assertEqual(fetch(status="refunded")["total"], 0)
        self.client.logout()
        self.assertEqual(self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code, 302)

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
            self.assertNotIn("paid-prediction-access-body", visible)
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
        self.assertContains(response, "paid-prediction-access-body")
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
