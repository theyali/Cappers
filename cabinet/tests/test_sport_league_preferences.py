from django.test import TestCase
from django.urls import reverse

from game.models import League, Match, Sport

from cabinet.forms import RegistrationForm
from cabinet.models import (
    AnalystProfile,
    User,
    UserLeaguePreference,
    UserSportPreference,
)
from cabinet.services.preferences import sync_user_sport_league_preferences


class SportLeaguePreferenceTests(TestCase):
    def setUp(self):
        self.football = Sport.objects.create(
            code="football-test",
            name="Football",
            name_ru="Футбол",
        )
        self.tennis = Sport.objects.create(
            code="tennis-test",
            name="Tennis",
            name_ru="Теннис",
        )
        self.premier_league = League.objects.create(
            external_id=990101,
            sport=self.football,
            name="Premier League",
            name_ru="Премьер-лига",
        )
        Match.objects.create(
            external_id=990201,
            sport=self.football,
            league=self.premier_league,
            sync_scope=Match.SyncScope.PREMATCH,
        )

    def test_reader_registration_allows_empty_sports(self):
        form = RegistrationForm(
            data={
                "username": "preference-reader",
                "email": "preference-reader@example.com",
                "password1": "safe-test-password-123",
                "password2": "safe-test-password-123",
                "role": User.Role.READER,
                "accept_terms": "on",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_capper_registration_requires_sport_even_if_role_is_tampered(self):
        form = RegistrationForm(
            data={
                "username": "preference-capper",
                "email": "preference-capper@example.com",
                "password1": "safe-test-password-123",
                "password2": "safe-test-password-123",
                "role": User.Role.READER,
                "accept_terms": "on",
            },
            require_sports=True,
        )

        form.is_valid()

        self.assertIn("sports", form.errors)

    def test_capper_registration_saves_preferences_and_legacy_fields(self):
        response = self.client.post(
            reverse("cabinet:register"),
            {
                "account_type": "capper",
                "username": "registered-capper",
                "email": "registered-capper@example.com",
                "password1": "safe-test-password-123",
                "password2": "safe-test-password-123",
                "role": User.Role.ANALYST,
                "sports": [self.football.id],
                "leagues": [self.premier_league.id],
                "accept_terms": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("cabinet:capper_onboarding", kwargs={"step": 1}),
        )
        user = User.objects.get(username="registered-capper")
        profile = AnalystProfile.objects.get(user=user)

        self.assertTrue(
            UserSportPreference.objects.filter(
                user=user,
                sport=self.football,
            ).exists()
        )
        self.assertTrue(
            UserLeaguePreference.objects.filter(
                user=user,
                league=self.premier_league,
            ).exists()
        )
        self.assertEqual(profile.favorite_sports, "Футбол")
        self.assertEqual(profile.favorite_leagues, "Премьер-лига")

    def test_capper_onboarding_step_three_replaces_preferences(self):
        tennis_league = League.objects.create(
            external_id=990103,
            sport=self.tennis,
            name="ATP Test League",
            name_ru="ATP тест",
        )
        Match.objects.create(
            external_id=990202,
            sport=self.tennis,
            league=tennis_league,
            sync_scope=Match.SyncScope.PREMATCH,
        )
        user = User.objects.create_user(
            username="onboarding-capper",
            password="safe-test-password",
            role=User.Role.READER,
        )
        profile = AnalystProfile.objects.create(
            user=user,
            display_name="Тестовый каппер",
            specialization="Теннис",
            bio="Описание профиля для теста.",
        )
        UserSportPreference.objects.create(user=user, sport=self.football)
        UserLeaguePreference.objects.create(user=user, league=self.premier_league)
        self.client.force_login(user)

        response = self.client.post(
            reverse("cabinet:capper_onboarding", kwargs={"step": 3}),
            {
                "sports": [self.tennis.id],
                "leagues": [tennis_league.id],
            },
        )

        self.assertRedirects(
            response,
            reverse("cabinet:capper_onboarding", kwargs={"step": 4}),
        )
        self.assertEqual(
            list(user.sport_preferences.values_list("sport_id", flat=True)),
            [self.tennis.id],
        )
        self.assertEqual(
            list(user.league_preferences.values_list("league_id", flat=True)),
            [tennis_league.id],
        )
        profile.refresh_from_db()
        self.assertEqual(profile.favorite_sports, "Теннис")
        self.assertEqual(profile.favorite_leagues, "ATP тест")

    def test_sync_preferences_updates_relations_and_legacy_display_fields(self):
        user = User.objects.create_user(
            username="preference-user",
            password="safe-test-password",
            role=User.Role.READER,
        )
        profile = AnalystProfile.objects.create(user=user)

        sync_user_sport_league_preferences(
            user,
            [self.football],
            [self.premier_league],
            profile=profile,
        )

        self.assertTrue(
            UserSportPreference.objects.filter(
                user=user,
                sport=self.football,
            ).exists()
        )
        self.assertTrue(
            UserLeaguePreference.objects.filter(
                user=user,
                league=self.premier_league,
            ).exists()
        )
        profile.refresh_from_db()
        self.assertEqual(profile.favorite_sports, "Футбол")
        self.assertEqual(profile.favorite_leagues, "Премьер-лига")

    def test_league_search_is_paginated(self):
        for index in range(40):
            league = League.objects.create(
                external_id=992000 + index,
                sport=self.football,
                name=f"League {index:02d}",
                name_ru=f"Лига {index:02d}",
            )
            Match.objects.create(
                external_id=993000 + index,
                sport=self.football,
                league=league,
                sync_scope=Match.SyncScope.PREMATCH,
            )

        response = self.client.get(reverse("cabinet:league_search"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 40)
        self.assertTrue(payload["has_more"])
        self.assertIn("is_top", payload["results"][0])

    def test_league_search_filters_by_sport_query_and_available_matches(self):
        League.objects.create(
            external_id=990102,
            sport=self.football,
            name="Premier League Archive",
            name_ru="Премьер-лига архив",
        )

        response = self.client.get(
            reverse("cabinet:league_search"),
            {
                "q": "Премьер",
                "sport": self.football.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [item["id"] for item in payload["results"]],
            [self.premier_league.id],
        )

    def test_league_search_top_uses_admin_order(self):
        first = League.objects.create(
            external_id=990104,
            sport=self.football,
            name="First Top League",
            name_ru="Первая топ-лига",
            is_top=True,
            top_order=20,
        )
        second = League.objects.create(
            external_id=990105,
            sport=self.tennis,
            name="Second Top League",
            name_ru="Вторая топ-лига",
            is_top=True,
            top_order=10,
        )
        for index, league in enumerate((first, second), start=1):
            Match.objects.create(
                external_id=990300 + index,
                sport=league.sport,
                league=league,
                sync_scope=Match.SyncScope.PREMATCH,
            )

        response = self.client.get(reverse("cabinet:league_search"), {"top": "1"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [item["id"] for item in payload["results"]],
            [second.id, first.id],
        )
        self.assertTrue(all(item["is_top"] for item in payload["results"]))
