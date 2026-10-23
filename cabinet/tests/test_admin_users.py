from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bots.models import BotAccount
from cabinet.models import ReferralVisit, User
from cabinet.presence import UserPresence
from cabinet.services.admin_users import build_admin_users_context
from payments.models import Payment


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AdminUsersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="admin", is_staff=True)
        cls.superuser = User.objects.create_user(username="super", is_superuser=True)
        cls.reader = User.objects.create_user(username="reader")
        cls.analyst = User.objects.create_user(username="analyst", role=User.Role.ANALYST)
        cls.bot = User.objects.create_user(username="bot")
        BotAccount.objects.create(user=cls.bot, kind=BotAccount.Kind.READER, is_active=False)

    def test_access_is_admin_only_and_private(self):
        url = reverse("cabinet:admin_users")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(url).status_code, 403)
        for admin in (self.admin, self.superuser):
            self.client.force_login(admin)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertContains(response, "Пользователи")

    def test_list_excludes_all_bots_and_admins_but_includes_analysts(self):
        rows = build_admin_users_context({})["rows"]
        self.assertEqual({row["username"] for row in rows}, {"reader", "analyst"})

    def test_investment_ignores_failed_test_and_refunded_payments_without_join_multiplication(self):
        for amount, status, is_test, refunded in (
            (100, Payment.Status.SUCCEEDED, False, False),
            (100, Payment.Status.SUCCEEDED, False, False),
            (700, Payment.Status.SUCCEEDED, True, False),
            (800, Payment.Status.FAILED, False, False),
            (900, Payment.Status.REFUNDED, False, True),
            (1000, Payment.Status.SUCCEEDED, False, True),
        ):
            Payment.objects.create(
                user=self.reader, provider=Payment.Provider.CLOUDPAYMENTS,
                purpose=Payment.Purpose.COIN_PACKAGE, amount=amount, amount_rub=amount,
                status=status, is_test=is_test,
                refunded_at=timezone.now() if refunded else None,
            )
        for session in ("one", "two"):
            ReferralVisit.objects.create(
                referrer=self.reader, visitor=self.analyst, session_key=session,
                registered_at=timezone.now(),
            )
        ReferralVisit.objects.create(referrer=self.reader, visitor=self.admin, session_key="click")
        row = next(row for row in build_admin_users_context({})["rows"] if row["username"] == "reader")
        self.assertEqual(row["invested_display"], "200")
        self.assertEqual(row["referrals_count"], 1)

    def test_presence_uses_last_activity_and_falls_back_to_login(self):
        recent = timezone.now() - timedelta(minutes=1)
        old = timezone.now() - timedelta(days=2)
        UserPresence.objects.create(user=self.reader, last_seen_at=recent)
        User.objects.filter(pk=self.analyst.pk).update(last_login=old)
        rows = {row["username"]: row for row in build_admin_users_context({})["rows"]}
        self.assertTrue(rows["reader"]["is_online"])
        self.assertEqual(rows["reader"]["last_seen_at"], recent)
        self.assertFalse(rows["analyst"]["is_online"])
        self.assertEqual(rows["analyst"]["last_seen_at"], old)
        self.assertEqual(rows["reader"]["registered_at"], self.reader.date_joined)

    def test_no_activity_and_no_payments_have_honest_defaults(self):
        row = next(row for row in build_admin_users_context({})["rows"] if row["username"] == "reader")
        self.assertIsNone(row["last_seen_at"])
        self.assertFalse(row["is_online"])
        self.assertEqual(row["invested_display"], "0")
        self.assertEqual(row["referrals_count"], 0)

    def test_pagination_clamps_invalid_pages_and_queries_are_bounded(self):
        User.objects.bulk_create([User(username=f"person-{number}") for number in range(51)])
        with self.assertNumQueries(3):
            context = build_admin_users_context({})
        self.assertEqual(len(context["rows"]), 50)
        last = build_admin_users_context({"page": "999"})
        self.assertEqual(last["users_page"].number, 2)
        self.assertEqual(len(last["rows"]), 3)
        self.assertEqual(build_admin_users_context({"page": "invalid"})["users_page"].number, 1)

    def test_both_navigation_variants_hide_link_from_readers(self):
        from django.template.loader import render_to_string
        from django.test import RequestFactory

        for template in ("_profile_tabs_sidebar.html", "_profile_tab_links.html"):
            for user, visible in ((self.reader, False), (self.admin, True)):
                request = RequestFactory().get("/")
                request.user = user
                html = render_to_string(f"cabinet/includes/{template}", {"request": request})
                self.assertEqual(reverse("cabinet:admin_users") in html, visible)
