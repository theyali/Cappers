import re

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from cabinet.forms import UserProfileForm
from cabinet.models import User

from .models import EmailChangeRequest


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
