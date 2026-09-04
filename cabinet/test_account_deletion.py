from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from wallets.models import CapperBalance
from wallets.services import ensure_virtual_balance

from .models import AnalystFollow, AnalystPaidSubscription, User


class AccountDeletionTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="delete-analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.user = User.objects.create_user(
            username="delete-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        AnalystFollow.objects.create(follower=self.user, analyst=self.analyst)
        AnalystPaidSubscription.objects.create(
            subscriber=self.user,
            analyst=self.analyst,
            price=Decimal("500.00"),
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        ensure_virtual_balance(self.user)

    def test_delete_account_requires_explicit_confirmation(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("cabinet:delete_account"))

        self.assertRedirects(
            response,
            f"{reverse('cabinet:profile')}?tab=settings",
            fetch_redirect_response=False,
        )
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_account_removes_user_and_related_database_rows(self):
        user_id = self.user.pk
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("cabinet:delete_account"),
            {"confirmation": "delete-account"},
        )

        self.assertRedirects(
            response,
            reverse("front:index"),
            fetch_redirect_response=False,
        )
        self.assertFalse(User.objects.filter(pk=user_id).exists())
        self.assertFalse(AnalystFollow.objects.filter(follower_id=user_id).exists())
        self.assertFalse(
            AnalystPaidSubscription.objects.filter(subscriber_id=user_id).exists()
        )
        self.assertFalse(CapperBalance.objects.filter(user_id=user_id).exists())
        self.assertNotIn("_auth_user_id", self.client.session)
