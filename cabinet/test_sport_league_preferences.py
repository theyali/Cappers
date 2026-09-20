from django.test import TestCase
from django.urls import reverse

from game.models import League, Sport

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

    def test_league_search_filters_by_sport_and_query(self):
        League.objects.create(
            external_id=990102,
            sport=self.tennis,
            name="ATP Tour",
            name_ru="ATP Тур",
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
