from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import PredictionCoupon
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant, TournamentResult
from tournaments.services.leaderboard import (
    finalize_finished_tournaments,
    finalize_tournament_results,
    tournament_leaderboard,
)
from wallets.models import RealBalanceTransaction


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

WIN = PredictionCoupon.StateStatus.WIN
LOSE = PredictionCoupon.StateStatus.LOSE
PENDING = PredictionCoupon.StateStatus.PENDING


class FinalizationTestCase(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            title="Final Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(days=3),
            ends_at=timezone.now() - timedelta(minutes=1),
            prize_first=Decimal("1000.00"),
            prize_second=Decimal("500.00"),
        )
        self.leader = self._participant("final-leader")
        self.runner = self._participant("final-runner")
        self.cheater = self._participant("final-cheater", TournamentParticipant.Status.DISQUALIFIED)
        self.quitter = self._participant("final-quitter", TournamentParticipant.Status.LEFT)
        self.leader_coupon = self._coupon(self.leader, WIN, payout="300")
        self.runner_coupon = self._coupon(self.runner, LOSE)
        self._coupon(self.cheater, WIN, payout="900")
        self._coupon(self.quitter, WIN, payout="800")

    def _participant(self, username, status=TournamentParticipant.Status.ACTIVE):
        user = User.objects.create_user(
            username=username,
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        return TournamentParticipant.objects.create(tournament=self.tournament, user=user, status=status)

    def _coupon(self, participant, state, payout="200"):
        coupon = PredictionCoupon.objects.create(
            author=participant.user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=state,
            total_stake=Decimal("100"),
            possible_payout=Decimal(payout),
            confidence=80,
            published_at=timezone.now() - timedelta(days=2),
        )
        TournamentCoupon.objects.create(tournament=self.tournament, participant=participant, coupon=coupon)
        return coupon

    def _real_balance(self, participant):
        participant.user.real_balance.refresh_from_db()
        return participant.user.real_balance.balance


class TournamentFinalizationTests(FinalizationTestCase):
    def test_only_active_participants_are_ranked(self):
        rows = tournament_leaderboard(self.tournament, use_cache=False)

        self.assertEqual([row["participant"] for row in rows], [self.leader, self.runner])

    def test_disqualified_participant_gets_no_prize(self):
        finalize_tournament_results(self.tournament)

        self.assertEqual(
            list(TournamentResult.objects.order_by("rank").values_list("participant", flat=True)),
            [self.leader.pk, self.runner.pk],
        )
        self.assertEqual(self._real_balance(self.leader), Decimal("1000.00"))
        self.assertEqual(self._real_balance(self.cheater), Decimal("0"))

    def test_finalization_waits_for_unsettled_coupons(self):
        pending = self._coupon(self.runner, PENDING)
        # Unsettled coupons of a disqualified participant do not hold the tournament.
        self._coupon(self.cheater, PENDING)

        with self.assertRaisesMessage(ValidationError, "Не рассчитано турнирных купонов: 1"):
            finalize_tournament_results(self.tournament)
        self.assertEqual(finalize_finished_tournaments()["waiting"], 1)
        self.tournament.refresh_from_db()
        self.assertIsNone(self.tournament.finalized_at)
        self.assertFalse(TournamentResult.objects.exists())

        PredictionCoupon.objects.filter(pk=pending.pk).update(state_status=LOSE)
        self.assertEqual(finalize_finished_tournaments()["finalized"], 1)
        self.tournament.refresh_from_db()
        self.assertIsNotNone(self.tournament.finalized_at)

    def test_results_are_fixed_once(self):
        finalize_tournament_results(self.tournament)
        # A later resettlement would put the runner first.
        PredictionCoupon.objects.filter(pk=self.leader_coupon.pk).update(state_status=LOSE)
        PredictionCoupon.objects.filter(pk=self.runner_coupon.pk).update(state_status=WIN)
        self.tournament.refresh_from_db()

        with self.assertRaisesMessage(ValidationError, "уже зафиксированы"):
            finalize_tournament_results(self.tournament)

        rows = tournament_leaderboard(self.tournament)
        self.assertEqual([row["participant"] for row in rows], [self.leader, self.runner])
        self.assertEqual(rows[0]["profit"], Decimal("200.00"))
        self.assertEqual(self._real_balance(self.leader), Decimal("1000.00"))
        self.assertEqual(self._real_balance(self.runner), Decimal("500.00"))
        self.assertEqual(
            RealBalanceTransaction.objects.filter(kind=RealBalanceTransaction.Kind.TOURNAMENT_PRIZE).count(),
            2,
        )

    def test_periodic_finalization_skips_running_and_draft_tournaments(self):
        Tournament.objects.create(
            title="Running Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1),
        )
        Tournament.objects.create(
            title="Draft Cup",
            status=Tournament.Status.DRAFT,
            starts_at=timezone.now() - timedelta(days=3),
            ends_at=timezone.now() - timedelta(days=1),
        )

        self.assertEqual(finalize_finished_tournaments(), {"finalized": 1, "waiting": 0, "errors": 0})
        self.assertEqual(Tournament.objects.filter(finalized_at__isnull=False).count(), 1)
        self.assertEqual(finalize_finished_tournaments()["finalized"], 0)


@override_settings(STORAGES=TEST_STORAGES)
class TournamentFinalizationAdminTests(FinalizationTestCase):
    def setUp(self):
        super().setUp()
        admin_user = User.objects.create_superuser(
            username="final-admin",
            password="safe-test-password",
            email="final-admin@example.com",
        )
        self.client.force_login(admin_user)

    def _finalize_action(self):
        return self.client.post(
            reverse("admin:tournaments_tournament_changelist"),
            {"action": "finalize_results", "_selected_action": [self.tournament.pk]},
            follow=True,
        )

    def test_admin_action_finalizes_and_reports_repeat(self):
        response = self._finalize_action()

        self.assertContains(response, "Итоги зафиксированы: 1.")
        self.assertEqual(self._real_balance(self.leader), Decimal("1000.00"))

        response = self._finalize_action()

        self.assertContains(response, "Итоги турнира уже зафиксированы.")
        self.assertEqual(self._real_balance(self.leader), Decimal("1000.00"))

    def test_results_page_shows_fixed_places(self):
        self._finalize_action()

        response = self.client.get(reverse("tournaments:results", kwargs={"slug": self.tournament.slug}))

        self.assertEqual(response.json()["total"], 2)
        self.assertContains(response, "final-leader")
        self.assertNotContains(response, "final-cheater")
