from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class TournamentPointsMigrationTests(TransactionTestCase):
    def test_existing_tournaments_keep_roi_results_and_snapshot_original_odds(self):
        old_target = [("tournaments", "0017_drop_access_type_and_flag_rule_types")]
        new_target = [("tournaments", "0018_tournament_points")]
        executor = MigrationExecutor(connection)
        other_targets = [target for target in executor.loader.graph.leaf_nodes() if target[0] != "tournaments"]
        old_target += other_targets
        new_target += other_targets
        executor.migrate(old_target)
        try:
            apps = executor.loader.project_state(old_target).apps
            user = apps.get_model("cabinet", "User").objects.create(username="migration-points", role="analyst")
            tournament = apps.get_model("tournaments", "Tournament").objects.create(title="Legacy Cup",
                slug="legacy-cup", starts_at=timezone.now()-timedelta(days=3),
                ends_at=timezone.now()-timedelta(days=1), finalized_at=timezone.now())
            participant = apps.get_model("tournaments", "TournamentParticipant").objects.create(tournament=tournament, user=user)
            coupon = apps.get_model("game", "PredictionCoupon").objects.create(author=user, published_at=timezone.now(),
                possible_payout=100, total_stake=100)
            for number, odds in enumerate(("2.80", "2.80")):
                match = apps.get_model("game", "Match").objects.create(external_id=999998 + number)
                apps.get_model("game", "Prediction").objects.create(coupon=coupon, match=match, coefficient=Decimal(odds),
                    stake=100, market="winner", selection="home")
            link = apps.get_model("tournaments", "TournamentCoupon").objects.create(tournament=tournament,
                participant=participant, coupon=coupon)
            result = apps.get_model("tournaments", "TournamentResult").objects.create(tournament=tournament,
                participant=participant, rank=1, profit=123, roi_percent=123, prize_amount=500)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(new_target)
        from tournaments.models import Tournament, TournamentCoupon, TournamentResult

        saved = Tournament.objects.get(pk=tournament.pk)
        self.assertEqual((saved.scoring_method, saved.daily_coupon_limit), ("roi", 0))
        self.assertEqual(TournamentCoupon.objects.get(pk=link.pk).published_coefficient, Decimal("7.84"))
        self.assertEqual(TournamentCoupon.objects.get(pk=link.pk).published_at, coupon.published_at)
        saved_result = TournamentResult.objects.get(pk=result.pk)
        self.assertEqual((saved_result.rank, saved_result.profit, saved_result.prize_amount), (1, 123, 500))
