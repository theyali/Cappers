from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from cabinet.models import (
    AnalystFollow,
    AnalystPaidSubscription,
    User,
    UserVipSubscription,
)
from cabinet.views import _profile_social_context


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
)
class ProfileSocialActionsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.now = timezone.now()
        self.viewer = User.objects.create_user(username="social-reader")
        self.capper = User.objects.create_user(
            username="social-capper", role=User.Role.ANALYST
        )
        self.client.force_login(self.viewer)

    def vip(self, user, **overrides):
        data = {
            "starts_at": self.now - timedelta(days=1),
            "ends_at": self.now + timedelta(days=29),
            "duration_days": 30,
            "source": UserVipSubscription.Source.ADMIN,
        }
        data.update(overrides)
        return UserVipSubscription.objects.create(user=user, **data)

    def social(self, user=None, **params):
        with patch("django.utils.timezone.now", return_value=self.now):
            return _profile_social_context(
                user or self.viewer, kind=params.pop("kind", "following"), **params
            )

    def toggle(self, active, user=None):
        return self.client.post(
            reverse(
                "cabinet:toggle_follow", kwargs={"user_id": (user or self.capper).pk}
            ),
            {"active": active},
        )

    def test_vip_directory_includes_unfollowed_cappers_and_readers_without_duplicates(
        self,
    ):
        reader = User.objects.create_user(username="vip-reader")
        self.vip(self.capper)
        self.vip(self.capper)
        self.vip(reader)
        context = self.social(filter_key="vip")
        self.assertEqual(context["profile_social_total"], 2)
        self.assertEqual(context["profile_social_metrics"]["total"], 0)
        self.assertEqual(context["profile_social_heading"], "VIP-пользователи")
        self.assertEqual(
            {row["username"] for row in context["profile_social_rows"]},
            {reader.username, self.capper.username},
        )
        rows = {row["username"]: row for row in context["profile_social_rows"]}
        self.assertTrue(rows[self.capper.username]["follow_url"])
        self.assertFalse(rows[reader.username]["follow_url"])

    def test_vip_directory_excludes_private_inactive_expired_and_future_accounts(self):
        self.vip(self.capper)
        private = User.objects.create_user(
            username="private-vip", role=User.Role.ANALYST
        )
        private.analyst_profile.is_public = False
        private.analyst_profile.save(update_fields=["is_public"])
        inactive = User.objects.create_user(username="inactive-vip", is_active=False)
        self.vip(private)
        self.vip(inactive)
        self.vip(User.objects.create_user(username="expired-vip"), ends_at=self.now)
        self.vip(
            User.objects.create_user(username="future-vip"),
            starts_at=self.now + timedelta(hours=1),
        )
        self.vip(User.objects.create_user(username="disabled-vip"), is_active=False)
        context = self.social(filter_key="vip")
        self.assertEqual(
            [row["username"] for row in context["profile_social_rows"]],
            [self.capper.username],
        )

    def test_vip_is_global_in_both_followers_and_following_panels(self):
        self.vip(self.capper)
        viewer = User.objects.create_user(
            username="viewer-capper", role=User.Role.ANALYST
        )
        for kind in ("followers", "following", "paid"):
            context = self.social(viewer, kind=kind, filter_key="vip")
            self.assertEqual(
                context["profile_social_rows"][0]["username"], self.capper.username
            )

    def test_vip_search_sort_and_pagination_are_applied_to_the_global_directory(self):
        for index in range(11):
            user = User.objects.create_user(
                username=f"search-vip-{index:02}", role=User.Role.ANALYST
            )
            self.vip(user, starts_at=self.now - timedelta(hours=index + 1))
        first = self.social(filter_key="vip", query="search-vip", sort="new")
        second = self.social(filter_key="vip", query="search-vip", sort="new", offset=8)
        self.assertEqual(first["profile_social_total"], 11)
        self.assertEqual(len(first["profile_social_rows"]), 8)
        self.assertEqual(first["profile_social_rows"][0]["username"], "search-vip-00")
        self.assertEqual(len(second["profile_social_rows"]), 3)
        loaded = self.social(filter_key="vip", limit=11)
        self.assertEqual(len(loaded["profile_social_rows"]), 11)

    def test_vip_directory_does_not_add_per_row_queries(self):
        self.vip(self.capper)
        with CaptureQueriesContext(connection) as one:
            self.social(filter_key="vip")
        for index in range(7):
            self.vip(
                User.objects.create_user(
                    username=f"more-vip-{index}", role=User.Role.ANALYST
                )
            )
        with CaptureQueriesContext(connection) as eight:
            self.social(filter_key="vip")
        self.assertEqual(len(one), len(eight))

    def test_reader_can_subscribe_unsubscribe_and_retry_both_explicit_states(self):
        with patch("cabinet.referral_views.mark_referral_subscription") as referral:
            for active in ("1", "1", "0", "0"):
                response = self.toggle(active)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["active"], active == "1")
                self.assertEqual(
                    AnalystFollow.objects.filter(
                        follower=self.viewer, analyst=self.capper
                    ).count(),
                    int(active),
                )
            referral.assert_called_once()

    def test_legacy_toggle_contract_is_preserved(self):
        url = reverse("cabinet:toggle_follow", kwargs={"user_id": self.capper.pk})
        self.assertTrue(self.client.post(url).json()["active"])
        self.assertFalse(self.client.post(url).json()["active"])

    def test_all_following_filters_render_working_unsubscribe_buttons(self):
        self.viewer.role = User.Role.ANALYST
        self.viewer.save(update_fields=["role"])
        AnalystFollow.objects.create(follower=self.viewer, analyst=self.capper)
        AnalystFollow.objects.create(follower=self.capper, analyst=self.viewer)
        self.vip(self.capper)
        AnalystPaidSubscription.objects.create(
            subscriber=self.viewer,
            analyst=self.capper,
            price=300,
            expires_at=self.now + timedelta(days=5),
        )
        AnalystPaidSubscription.objects.create(
            subscriber=self.capper,
            analyst=self.viewer,
            price=300,
            expires_at=self.now + timedelta(days=5),
        )
        for kind in ("following", "followers"):
            for filter_key in ("all", "cappers", "mutual", "paid", "vip"):
                context = self.social(kind=kind, filter_key=filter_key)
                row = next(
                    row
                    for row in context["profile_social_rows"]
                    if row["id"] == self.capper.pk
                )
                self.assertEqual(row["follow_label"], "Отписаться")
                self.assertTrue(row["follow_url"])
                html = render_to_string(
                    "cabinet/includes/_profile_social_rows.html",
                    {"profile_social_rows": [row]},
                )
                self.assertIn("data-profile-social-follow-url", html)
                self.assertIn("Отписаться", html)

    def test_unsubscribe_does_not_cancel_paid_access(self):
        AnalystFollow.objects.create(follower=self.viewer, analyst=self.capper)
        subscription = AnalystPaidSubscription.objects.create(
            subscriber=self.viewer,
            analyst=self.capper,
            price=300,
            expires_at=self.now + timedelta(days=5),
        )
        self.assertFalse(self.toggle("0").json()["active"])
        row = self.social(filter_key="paid")["profile_social_rows"][0]
        self.assertFalse(row["is_following"])
        self.assertEqual(row["follow_label"], "Подписаться")
        self.assertIsNotNone(row["paid_subscription"])
        subscription.refresh_from_db()
        self.assertEqual(subscription.expires_at, self.now + timedelta(days=5))

    def test_permissions_invalid_state_and_self_follow(self):
        self.assertEqual(self.toggle("unexpected").status_code, 400)
        self.assertEqual(self.toggle("1", self.viewer).status_code, 404)
        self.client.force_login(self.capper)
        self.assertEqual(self.toggle("1").status_code, 400)
        self.client.logout()
        self.assertEqual(self.toggle("1").status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.viewer)
        self.assertEqual(
            csrf_client.post(
                reverse("cabinet:toggle_follow", kwargs={"user_id": self.capper.pk}),
                {"active": "1"},
            ).status_code,
            403,
        )

    def test_vip_ajax_returns_global_heading_and_requested_window(self):
        self.vip(self.capper)
        response = self.client.get(
            reverse("cabinet:profile_social"), {"filter": "vip", "limit": 16}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["heading"], "VIP-пользователи")
        self.assertIn(self.capper.username, response.json()["html"])
        self.assertIn("Подписаться", response.json()["html"])
