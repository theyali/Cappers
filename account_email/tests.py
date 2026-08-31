import re
from urllib.parse import urlsplit

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from cabinet.forms import UserProfileForm
from cabinet.models import User

from .models import EmailChangeRequest, PasswordResetRequest


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    STORAGES=TEST_STORAGES,
)
class AccountEmailFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="email-user",
            password="test-password",
            email="",
        )

    def _code_from_last_email(self):
        message = mail.outbox[-1].body
        match = re.search(r"\b(\d{6})\b", message)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_profile_form_does_not_edit_email_directly(self):
        form = UserProfileForm(
            {"first_name": "New", "last_name": "Name", "email": "direct@example.com"},
            instance=self.user,
        )

        self.assertTrue(form.is_valid())
        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "")

    def test_user_can_add_email_with_code(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("account_email:add"),
            {"new_email": "New.Email@Example.com"},
        )

        flow = EmailChangeRequest.objects.get(user=self.user)
        self.assertRedirects(response, reverse("account_email:verify", kwargs={"request_id": flow.pk}))
        self.assertEqual(flow.new_email, "new.email@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new.email@example.com"])

        response = self.client.post(
            reverse("account_email:verify", kwargs={"request_id": flow.pk}),
            {"code": self._code_from_last_email()},
        )

        self.assertRedirects(response, f"{reverse('cabinet:profile')}?tab=settings")
        self.user.refresh_from_db()
        flow.refresh_from_db()
        self.assertEqual(self.user.email, "new.email@example.com")
        self.assertIsNotNone(flow.completed_at)

    def test_user_changes_email_after_current_email_link(self):
        self.user.email = "old@example.com"
        self.user.save(update_fields=["email"])
        self.client.force_login(self.user)

        response = self.client.post(reverse("account_email:request_change"))

        self.assertRedirects(response, f"{reverse('cabinet:profile')}?tab=settings")
        flow = EmailChangeRequest.objects.get(user=self.user)
        self.assertEqual(mail.outbox[0].to, ["old@example.com"])
        self.assertIn(flow.current_token, mail.outbox[0].body)

        response = self.client.post(
            reverse("account_email:confirm_change", kwargs={"token": flow.current_token}),
            {"new_email": "updated@example.com"},
        )

        self.assertRedirects(response, reverse("account_email:verify", kwargs={"request_id": flow.pk}))
        flow.refresh_from_db()
        self.assertEqual(flow.new_email, "updated@example.com")
        self.assertEqual(mail.outbox[-1].to, ["updated@example.com"])

        response = self.client.post(
            reverse("account_email:verify", kwargs={"request_id": flow.pk}),
            {"code": self._code_from_last_email()},
        )

        self.assertRedirects(response, f"{reverse('cabinet:profile')}?tab=settings")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "updated@example.com")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    STORAGES=TEST_STORAGES,
)
class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reset-user",
            password="old-password-2026",
            email="reset@example.com",
        )

    def _request_reset(self):
        response = self.client.post(
            reverse("cabinet:password_reset"),
            {"email": self.user.email},
        )
        self.assertRedirects(response, reverse("cabinet:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn("одноразовую ссылку", mail.outbox[0].body)

        match = re.search(r"https?://[^\s]+", mail.outbox[0].body)
        self.assertIsNotNone(match)
        return PasswordResetRequest.objects.get(user=self.user), urlsplit(match.group(0)).path

    def test_reset_request_for_unknown_email_does_not_leak_account(self):
        response = self.client.post(
            reverse("cabinet:password_reset"),
            {"email": "missing@example.com"},
        )

        self.assertRedirects(response, reverse("cabinet:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(PasswordResetRequest.objects.exists())

    def test_email_link_is_consumed_on_first_open(self):
        flow, link_path = self._request_reset()

        response = self.client.get(link_path)
        self.assertRedirects(response, reverse("cabinet:password_reset_set"))
        flow.refresh_from_db()
        self.assertIsNotNone(flow.opened_at)

        second_browser = Client()
        response = second_browser.get(link_path)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ссылка уже не работает")

        response = self.client.get(reverse("cabinet:password_reset_set"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Задайте новый пароль")

    def test_user_can_set_new_password_after_opening_link(self):
        flow, link_path = self._request_reset()
        self.client.get(link_path)

        response = self.client.post(
            reverse("cabinet:password_reset_set"),
            {
                "new_password1": "New-secure-password-2026",
                "new_password2": "New-secure-password-2026",
            },
        )

        self.assertRedirects(response, reverse("cabinet:password_reset_complete"))
        flow.refresh_from_db()
        self.user.refresh_from_db()
        self.assertIsNotNone(flow.completed_at)
        self.assertTrue(self.user.check_password("New-secure-password-2026"))

        response = self.client.get(reverse("cabinet:password_reset_set"))
        self.assertContains(response, "Ссылка уже не работает")

    def test_new_request_revokes_previous_reset_session(self):
        first_flow, first_link = self._request_reset()
        self.client.get(first_link)

        mail.outbox.clear()
        second_flow, _ = self._request_reset()

        first_flow.refresh_from_db()
        self.assertIsNotNone(first_flow.revoked_at)
        self.assertNotEqual(first_flow.pk, second_flow.pk)

        response = self.client.get(reverse("cabinet:password_reset_set"))
        self.assertContains(response, "Ссылка уже не работает")

    def test_set_password_page_requires_consumed_email_link(self):
        response = self.client.get(reverse("cabinet:password_reset_set"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ссылка уже не работает")
