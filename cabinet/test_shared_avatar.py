from django.test import TestCase
from django.urls import reverse

from .models import User


class SharedAccountAvatarTests(TestCase):
    def test_existing_reader_photo_is_reused_when_capper_onboarding_starts(self):
        user = User.objects.create_user(
            username="reader-with-photo",
            password="safe-test-password",
            role=User.Role.READER,
            avatar="users/avatars/shared-reader.jpg",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("cabinet:become_capper_start"))

        self.assertRedirects(response, reverse("cabinet:capper_onboarding", args=[1]))
        user.refresh_from_db()
        profile = user.analyst_profile
        self.assertEqual(profile.avatar.name, user.avatar.name)

        step_response = self.client.get(reverse("cabinet:capper_onboarding", args=[1]))
        self.assertContains(step_response, "Изменить фото (необязательно)")
        self.assertContains(step_response, "Фото аккаунта уже используется")

    def test_new_capper_photo_updates_the_same_account_photo(self):
        user = User.objects.create_user(
            username="capper-shared-photo",
            password="safe-test-password",
            role=User.Role.ANALYST,
            avatar="users/avatars/original.jpg",
        )
        profile = user.analyst_profile
        profile.avatar = "analysts/avatars/replacement.jpg"
        profile.save(update_fields=["avatar", "updated_at"])

        user.refresh_from_db()
        profile.refresh_from_db()

        self.assertEqual(user.avatar.name, "analysts/avatars/replacement.jpg")
        self.assertEqual(profile.avatar.name, user.avatar.name)

    def test_account_photo_change_is_mirrored_back_to_capper_profile(self):
        user = User.objects.create_user(
            username="capper-account-photo",
            password="safe-test-password",
            role=User.Role.ANALYST,
            avatar="users/avatars/first.jpg",
        )
        user.avatar = "users/avatars/second.jpg"
        user.save(update_fields=["avatar"])

        user.analyst_profile.refresh_from_db()
        self.assertEqual(user.analyst_profile.avatar.name, user.avatar.name)
