from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournaments.models import (
    Tournament,
    TournamentAchievement,
    TournamentParticipant,
    TournamentResult,
)

from .models import User


class ExpertPublicTournamentTabsTests(TestCase):
    def test_public_profile_exposes_achievements_and_tournament_history(self):
        analyst = User.objects.create_user(
            username="tournament-expert",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        now = timezone.now()

        active_tournament = Tournament.objects.create(
            title="Активный кубок",
            status=Tournament.Status.PUBLISHED,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=2),
        )
        TournamentParticipant.objects.create(
            tournament=active_tournament,
            user=analyst,
        )

        finished_tournament = Tournament.objects.create(
            title="Завершённый кубок",
            status=Tournament.Status.PUBLISHED,
            starts_at=now - timedelta(days=10),
            ends_at=now - timedelta(days=2),
        )
        finished_participant = TournamentParticipant.objects.create(
            tournament=finished_tournament,
            user=analyst,
        )
        achievement = TournamentAchievement.objects.create(
            tournament=finished_tournament,
            title="Серебро турнира",
            kind=TournamentAchievement.Kind.SECOND_PLACE,
        )
        TournamentResult.objects.create(
            tournament=finished_tournament,
            participant=finished_participant,
            rank=2,
            coupons_count=7,
            wins_count=4,
            losses_count=2,
            refunds_count=1,
            profit="350.00",
            roi_percent="14.50",
            prize_amount="5000.00",
            achievement=achievement,
        )

        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["expert_current_tournaments"]), 1)
        self.assertEqual(len(response.context["expert_finished_tournaments"]), 1)
        self.assertEqual(response.context["expert_finished_tournaments"][0]["rank"], 2)
        self.assertEqual(len(response.context["expert_tournament_achievements"]), 1)
        self.assertContains(response, 'data-expert-public-tab="achievements"')
        self.assertContains(response, 'data-expert-public-tab="tournaments"')
        self.assertContains(response, "Активный кубок")
        self.assertContains(response, "Завершённый кубок")
        self.assertContains(response, "Серебро турнира")
