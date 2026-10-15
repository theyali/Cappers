from decimal import Decimal
from html.parser import HTMLParser
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone


class CouponMarkupParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes = []
        self.anchor_depth = 0
        self.nested_controls = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.nodes.append((tag, attrs))
        if tag in {"a", "button"} and self.anchor_depth:
            self.nested_controls = True
        if tag == "a":
            self.anchor_depth += 1

    def handle_endtag(self, tag):
        if tag == "a":
            self.anchor_depth -= 1

    def by_class(self, name):
        return [(tag, attrs) for tag, attrs in self.nodes if name in attrs.get("class", "").split()]


class PredictionMobileCouponTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/predictions/?sport=football")
        self.request.user = SimpleNamespace(is_authenticated=True)
        self.author = SimpleNamespace(username="expert-test", avatar=None, is_vip=False)
        self.coupon = SimpleNamespace(id=101, author=self.author, author_id=51, comments_count=7)
        self.prediction = SimpleNamespace(
            coupon=self.coupon, coefficient=Decimal("1.85"), market="Исход матча", selection="П1",
            state_status="win", is_own=False, is_liked=False, is_favorite=False,
            likes_count=4, comments_count=7, shares_count=3,
            expert_name="Тестовый эксперт", expert_initials="ТЭ", expert_avatar_url="",
            expert_trust_index=None, expert_verified=False,
            match=SimpleNamespace(
                home_team_name="Первая команда", away_team_name="Вторая команда",
                starts_at=timezone.now(), score="2-1", sport=SimpleNamespace(code="football", name="Football", name_ru="Футбол"),
            ),
        )

    def render(self, template="front/includes/_prediction_mobile_coupon.html"):
        html = render_to_string(template, {"prediction": self.prediction, "request": self.request})
        return html, CouponMarkupParser(html)

    def test_compact_card_has_author_and_three_actions_below_copy(self):
        html, parsed = self.render()
        self.assertEqual(len(parsed.by_class("expert-mobile-coupon")), 1)
        self.assertIn("Первая команда — Вторая команда", html)
        self.assertIn("Тестовый эксперт", html)
        self.assertIn(reverse("front:expert_profile", kwargs={"username": self.author.username}), html)
        self.assertEqual(len(parsed.by_class("prediction-like")), 1)
        self.assertEqual(len(parsed.by_class("prediction-comment-metric")), 1)
        self.assertEqual(len(parsed.by_class("prediction-share")), 1)
        self.assertEqual(parsed.by_class("prediction-favorite"), [])
        self.assertEqual(parsed.by_class("prediction-views"), [])
        self.assertLess(html.index('class="expert-mobile-coupon-copy"'), html.index('class="prediction-reactions'))
        self.assertFalse(parsed.nested_controls)

    def test_comment_and_share_use_existing_endpoints_and_counters(self):
        html, parsed = self.render()
        comment = parsed.by_class("prediction-comment-metric")[0][1]
        share = parsed.by_class("prediction-share")[0][1]
        self.assertEqual(comment["href"], reverse("front:prediction_detail", args=[101]) + "#comments")
        self.assertEqual(share["data-share-url"], reverse("front:prediction_detail", args=[101]))
        self.assertEqual(share["data-share-endpoint"], reverse("front:prediction_share", args=[101]))
        self.assertIn('data-comment-count="101">7</span>', html)
        self.assertIn('data-share-count>3</b>', html)

    def test_own_like_is_disabled_and_other_like_is_enabled(self):
        self.prediction.is_own = True
        _, parsed = self.render()
        button = parsed.by_class("prediction-like")[0][1]
        self.assertIn("disabled", button)
        self.assertEqual(button["aria-disabled"], "true")
        self.prediction.is_own = False
        _, parsed = self.render()
        self.assertNotIn("disabled", parsed.by_class("prediction-like")[0][1])

    def test_liked_state_and_anonymous_login_are_preserved(self):
        self.prediction.is_liked = True
        self.request.user.is_authenticated = False
        _, parsed = self.render()
        button = parsed.by_class("prediction-like")[0][1]
        self.assertEqual(button["aria-pressed"], "true")
        self.assertIn("is-active", button["class"].split())
        self.assertEqual(button["data-authenticated"], "false")
        self.assertIn("next=", button["data-login-url"])
        self.assertEqual(button["data-url"], reverse("front:prediction_like", args=[101]))

    def test_author_avatar_and_initials_fallback(self):
        html, _ = self.render()
        self.assertIn("ТЭ", html)
        self.prediction.expert_avatar_url = "/media/avatar.webp"
        _, parsed = self.render()
        image = next(attrs for tag, attrs in parsed.nodes if tag == "img")
        self.assertEqual(image["src"], "/media/avatar.webp")
        self.assertEqual((image["width"], image["height"]), ("30", "30"))

    def test_missing_sport_and_long_names_render_safely(self):
        self.prediction.match.sport = None
        self.prediction.expert_name = '<script>alert("x")</script>'
        html, parsed = self.render()
        self.assertIn("Спорт", html)
        self.assertNotIn("<script>", html)
        self.assertFalse(parsed.nested_controls)

    def test_desktop_markup_and_existing_action_buttons_remain_present(self):
        _, parsed = self.render("front/includes/_prediction_table_row.html")
        for name in ("prediction-table-desktop", "prediction-table-event", "prediction-table-pick", "prediction-table-status"):
            self.assertEqual(len(parsed.by_class(name)), 1)
        self.assertEqual(len(parsed.by_class("prediction-mobile-coupon")), 1)
        self.assertFalse(parsed.nested_controls)

    def test_personal_profile_mobile_coupon_has_no_author_or_reaction_buttons(self):
        coupon = SimpleNamespace(id=101, sport_name="Футбол", sport_code="football", starts_at=timezone.now(),
                                 title="Мой прогноз", subtitle="П1", state_status="win", state_label="Выигрыш",
                                 coefficient=Decimal("1.85"), score="2-1")
        html = render_to_string("cabinet/includes/_profile_mobile_coupon_items.html", {"mobile_coupons": [coupon]})
        parsed = CouponMarkupParser(html)
        self.assertEqual(len(parsed.by_class("expert-mobile-coupon")), 1)
        self.assertFalse(any(tag == "button" for tag, _ in parsed.nodes))
        self.assertEqual(parsed.by_class("prediction-mobile-coupon-author"), [])
        self.assertEqual(parsed.by_class("prediction-reactions"), [])

    def test_full_reaction_component_keeps_detail_page_actions(self):
        html = render_to_string("front/includes/_coupon_reactions.html", {
            "coupon": self.coupon, "show_comments": True, "request": self.request,
            "likes_count": 4, "shares_count": 3, "favorites_count": 2, "views_count": 10,
        })
        parsed = CouponMarkupParser(html)
        self.assertEqual(len(parsed.by_class("prediction-favorite")), 1)
        self.assertEqual(len(parsed.by_class("prediction-views")), 1)
        self.assertEqual(parsed.by_class("prediction-comment-metric")[0][1]["href"], "#comments")


class PredictionMobileLikePermissionTests(TestCase):
    def setUp(self):
        from cabinet.models import User
        from game.models import Match, Prediction, PredictionCoupon

        self.author = User.objects.create_user(username="mobile-author", password="test-password", role=User.Role.ANALYST)
        self.reader = User.objects.create_user(username="mobile-reader", password="test-password")
        coupon = PredictionCoupon.objects.create(
            author=self.author, published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.FREE, total_stake=Decimal("10"), possible_payout=Decimal("18.50"),
        )
        match = Match.objects.create(external_id=9050101, sync_scope=Match.SyncScope.PREMATCH)
        Prediction.objects.create(coupon=coupon, match=match, market="winner", selection="home",
                                  coefficient=Decimal("1.85"), stake=Decimal("10"))
        self.like_url = reverse("front:prediction_like", args=[coupon.pk])

    def test_author_cannot_like_own_coupon_via_direct_request(self):
        from front.models import PredictionLike

        self.client.force_login(self.author)
        response = self.client.post(self.like_url)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["active"])
        self.assertFalse(PredictionLike.objects.exists())

    def test_other_reader_can_toggle_like(self):
        self.client.force_login(self.reader)
        response = self.client.post(self.like_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["active"])
        self.assertEqual(response.json()["count"], 1)
        response = self.client.post(self.like_url)
        self.assertFalse(response.json()["active"])
        self.assertEqual(response.json()["count"], 0)
