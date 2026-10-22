from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon
from game.services.settlement import cancel_published_coupon, resettle_coupon, settle_coupon
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant, TournamentPointAccrual, TournamentPrize
from tournaments.services.coupons import attach_coupon_to_tournament
from tournaments.services.leaderboard import finalize_tournament_results, tournament_leaderboard, user_tournament_positions
from tournaments.services.participants import build_tournament_participants_context
from tournaments.services.points import sync_participant_points


class PointsFixtures:
    def setUp(self):
        cache.clear()
        self.tournament = Tournament.objects.create(title="Points Cup", status="published",
            starts_at=timezone.now() - timedelta(days=5), ends_at=timezone.now() + timedelta(days=5))
        self.participant = self.member("points-capper")

    def member(self, username):
        user = User.objects.create_user(username=username, role=User.Role.ANALYST)
        return TournamentParticipant.objects.create(tournament=self.tournament, user=user)

    def coupon(self, state="win", odds=("1.92",), *, participant=None, published_at=None, attach=False):
        participant = participant or self.participant
        coupon = PredictionCoupon.objects.create(author=participant.user, tournament=self.tournament,
            published_status="published", state_status=state, total_stake=100, possible_payout=200,
            published_at=published_at or timezone.now())
        for coefficient in odds:
            match = Match.objects.create(external_id=990000 + Match.objects.count(), sync_scope=Match.SyncScope.PREMATCH,
                starts_at=timezone.now() + timedelta(hours=2))
            Prediction.objects.create(coupon=coupon, match=match, coefficient=Decimal(coefficient),
                market="winner", selection="home", stake=100,
                state_status={"win": "win", "lose": "lose", "refund": "refund", "pending": ""}[state])
        link = (attach_coupon_to_tournament(coupon, self.tournament) if attach else
            TournamentCoupon.objects.create(tournament=self.tournament, participant=participant, coupon=coupon))
        return coupon, link

    def row(self, participant=None):
        return next(row for row in tournament_leaderboard(self.tournament, use_cache=False)
            if row["participant"].pk == (participant or self.participant).pk)


class TournamentPointsTests(PointsFixtures, TestCase):
    def test_examples_and_high_odds_bonus(self):
        self.coupon(odds=("1.92",))
        self.coupon(odds=("2.40",))
        self.coupon("lose")
        _, link = self.coupon(odds=("2.80", "2.80"))
        self.assertEqual(link.published_coefficient, Decimal("7.84"))
        row = self.row()
        self.assertEqual((row["base_points"], row["bonus_points"], row["points"]), (116, 15, 131))

    def test_refund_pending_and_strict_high_odds_threshold(self):
        for state, odds, expected in (("refund", "7.84", 0), ("pending", "7.84", 0),
                ("win", "3.00", 30), ("win", "3.01", 45), ("lose", "9.99", -5)):
            with self.subTest(state=state, odds=odds):
                member = self.member(f"case-{state}-{odds}")
                self.coupon(state, (odds,), participant=member)
                self.assertEqual(self.row(member)["points"], expected)

    def test_snapshot_ignores_line_and_payout_changes(self):
        coupon, link = self.coupon(odds=("1.92", "2.40"))
        coupon.predictions.update(coefficient=Decimal("9.99"))
        coupon.possible_payout = Decimal("100.00")
        coupon.save()
        self.assertEqual(self.row()["points"], 61)  # floor(4.608 * 10) + 15
        link.refresh_from_db()
        self.assertEqual(link.published_coefficient, Decimal("4.608"))

    def test_streak_disjoint_triples_and_refund_break(self):
        for _ in range(6):
            self.coupon()
        self.assertEqual(self.participant.point_accruals.filter(kind="streak").count(), 2)
        self.coupon("refund")
        self.coupon()
        self.coupon()
        self.assertEqual(self.participant.point_accruals.filter(kind="streak").count(), 2)

    def test_out_of_order_settlement_recomputes_following_streaks(self):
        first, _ = self.coupon("pending")
        self.coupon()
        self.coupon()
        self.assertFalse(self.participant.point_accruals.filter(kind="streak").exists())
        first.predictions.update(state_status="win")
        settle_coupon(first.pk)
        self.assertEqual(self.row()["points"], 67)
        first.predictions.update(state_status="refund")
        resettle_coupon(first.pk, recalculate_predictions=False)
        self.assertEqual(self.row()["points"], 38)

    def test_repeat_settlement_preserves_accrual_identity(self):
        coupon, _ = self.coupon()
        initial = list(self.participant.point_accruals.values_list("id", "points"))
        for _ in range(3):
            resettle_coupon(coupon.pk, recalculate_predictions=False)
        self.assertEqual(list(self.participant.point_accruals.values_list("id", "points")), initial)

    def test_resettlement_back_to_pending_revokes_points(self):
        coupon, _ = self.coupon()
        coupon.predictions.update(state_status="")
        resettle_coupon(coupon.pk, recalculate_predictions=False)
        self.assertEqual(self.row()["points"], 0)
        self.assertFalse(self.participant.point_accruals.exists())

    def test_daily_bonus_counts_published_pending_and_refunds_once(self):
        for state in ("pending", "refund", "lose", "pending", "refund", "pending"):
            self.coupon(state)
        for _ in range(3):
            sync_participant_points(self.participant.pk)
        self.assertEqual(self.row()["base_points"], -5)
        self.assertEqual(self.row()["bonus_points"], 5)
        self.assertEqual(self.participant.point_accruals.filter(kind="daily").count(), 1)

    def test_daily_bonus_uses_tournament_timezone_not_active_timezone(self):
        before_midnight = datetime(2026, 10, 22, 19, 59, tzinfo=dt_timezone.utc)
        for _ in range(4):
            self.coupon("pending", published_at=before_midnight)
        with timezone.override("America/New_York"):
            self.coupon("pending", published_at=before_midnight + timedelta(minutes=2))
        self.assertEqual(self.row()["bonus_points"], 0)
        self.coupon("pending", published_at=before_midnight)
        self.assertEqual(self.row()["bonus_points"], 5)

    def test_cancellation_revokes_daily_bonus_and_frees_match(self):
        coupons = [self.coupon("pending")[0] for _ in range(5)]
        self.assertEqual(self.row()["points"], 5)
        cancel_published_coupon(coupons[-1].pk)
        self.assertEqual(self.row()["points"], 0)
        self.assertEqual(self.row()["coupons_count"], 4)

    def test_bonus_flags_and_configured_amounts(self):
        self.tournament.streak_bonus_points = 23
        self.tournament.high_odds_bonus_points = 17
        self.tournament.daily_bonus_points = 9
        self.tournament.save()
        for _ in range(5):
            self.coupon(odds=("4.00",))
        self.assertEqual(self.row()["bonus_points"], 5 * 17 + 23 + 9)
        # Separate tournament: rules are immutable after publication.
        self.tournament = Tournament.objects.create(title="No bonuses", status="published",
            starts_at=timezone.now()-timedelta(days=1), ends_at=timezone.now()+timedelta(days=1),
            streak_bonus_enabled=False, high_odds_bonus_enabled=False, daily_bonus_enabled=False)
        self.participant = self.member("no-bonuses")
        for _ in range(5):
            self.coupon(odds=("4.00",))
        self.assertEqual(self.row()["points"], 200)

    def test_points_rank_before_profit_and_tie_break_by_wins_then_join_order(self):
        other = self.member("points-other")
        self.coupon(odds=("2.00",))
        self.coupon(odds=("1.00",), participant=other)
        self.coupon(odds=("1.00",), participant=other)
        rows = tournament_leaderboard(self.tournament, use_cache=False)
        self.assertEqual([row["participant"].pk for row in rows], [other.pk, self.participant.pk])
        other.tournament_coupons.all().delete()
        self.coupon(odds=("2.00",), participant=other)
        self.assertEqual(self.row()["rank"], 1)

    def test_no_predictions_and_pending_rank_below_negative_results(self):
        empty = self.member("points-empty")
        self.coupon("lose")
        self.assertEqual(self.row()["rank"], 1)
        self.assertEqual(self.row(empty)["rank"], 2)

    def test_idle_participant_receives_no_money_coins_vip_or_achievement(self):
        self.tournament.ends_at = timezone.now() - timedelta(seconds=1)
        self.tournament.save()
        TournamentPrize.objects.create(tournament=self.tournament, place=1, money_amount=500,
            coins_amount=200, vip_days=10)
        results = finalize_tournament_results(self.tournament)
        self.assertEqual(results[0].prize_amount, 0)
        self.assertFalse(self.tournament.prize_awards.exists())

    def test_equal_points_wins_and_join_time_use_participant_id(self):
        other = self.member("points-equal")
        TournamentParticipant.objects.filter(pk=other.pk).update(joined_at=self.participant.joined_at)
        self.coupon()
        self.coupon(participant=other)
        self.assertEqual(self.row()["rank"], 1)

    def test_leave_and_disqualification_invalidate_warm_cache_and_revoke_points(self):
        self.coupon()
        tournament_leaderboard(self.tournament)
        for status in ("left", "disqualified"):
            self.participant.status = status
            self.participant.save()
            self.assertEqual(tournament_leaderboard(self.tournament), [])
            self.assertFalse(self.participant.point_accruals.exists())
            self.participant.status = "active"
            self.participant.save()
            self.assertEqual(self.row()["points"], 19)

    def test_settlement_invalidates_warm_cache(self):
        coupon, _ = self.coupon("pending")
        self.assertEqual(tournament_leaderboard(self.tournament)[0]["points"], 0)
        coupon.predictions.update(state_status="win")
        settle_coupon(coupon.pk)
        self.assertEqual(tournament_leaderboard(self.tournament)[0]["points"], 19)

    def test_user_positions_match_points_and_frozen_results_in_two_queries(self):
        self.coupon()
        with self.assertNumQueries(2):
            position = user_tournament_positions(self.participant.user, [self.tournament.pk])[self.tournament.pk]
        self.assertEqual(position["points"], 19)
        self.tournament.ends_at = timezone.now() - timedelta(seconds=1)
        self.tournament.save()
        finalize_tournament_results(self.tournament)
        PredictionCoupon.objects.filter(tournament=self.tournament).update(state_status="lose")
        with self.assertNumQueries(2):
            position = user_tournament_positions(self.participant.user, [self.tournament.pk])[self.tournament.pk]
        self.assertEqual(position["points"], 19)

    def test_finalized_points_and_prizes_are_frozen_and_paid_once(self):
        coupon, _ = self.coupon()
        TournamentPrize.objects.create(tournament=self.tournament, place=1, coins_amount=200)
        self.tournament.ends_at = timezone.now()-timedelta(seconds=1)
        self.tournament.save()
        result = finalize_tournament_results(self.tournament)[0]
        self.assertEqual((result.base_points, result.bonus_points, result.points), (19, 0, 19))
        coupon.predictions.update(state_status="lose")
        resettle_coupon(coupon.pk, recalculate_predictions=False)
        self.tournament.refresh_from_db()
        self.assertEqual(tournament_leaderboard(self.tournament)[0]["points"], 19)
        with self.assertRaises(ValidationError):
            finalize_tournament_results(self.tournament)
        self.assertEqual(self.tournament.prize_awards.count(), 1)

    def test_legacy_roi_still_ranks_by_roi(self):
        self.tournament.scoring_method = "roi"
        self.tournament.daily_coupon_limit = 0
        self.tournament.save()
        other = self.member("roi-other")
        coupon, _ = self.coupon(odds=("9.99",))
        coupon.possible_payout = 110
        coupon.save()
        self.coupon(odds=("1.01",), participant=other)
        self.assertEqual(self.row(other)["rank"], 1)
        self.assertFalse(TournamentPointAccrual.objects.exists())

    def test_participants_show_real_points_breakdown_and_prize_gap(self):
        other = self.member("points-leader")
        self.coupon("lose")
        self.coupon(participant=other)
        TournamentPrize.objects.create(tournament=self.tournament, place=1, money_amount=100)
        request = RequestFactory().get("/")
        request.user = self.participant.user
        context = build_tournament_participants_context(request, self.tournament)
        self.assertEqual(context["own"]["points_label"], "-5")
        self.assertEqual(context["gap_label"], "24 очков")
        self.assertEqual(context["metric_label"], "Очки")

    def test_pages_and_ajax_show_points_and_configured_rules(self):
        self.tournament.streak_bonus_points = 27
        self.tournament.daily_coupon_limit = 8
        self.tournament.save()
        self.coupon()
        self.client.force_login(self.participant.user)
        response = self.client.get(self.tournament.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Всего очков")
        self.assertContains(response, "+27")
        self.assertContains(response, "Дневной лимит: 8")
        self.assertContains(response, "Asia/Baku")
        self.assertEqual(response.context["results_tab"]["rows"][0]["points"], 19)
        results = self.client.get(reverse("tournaments:results", kwargs={"slug": self.tournament.slug})).json()
        self.assertIn("Всего очков", results["html"])
        directory = self.client.get(reverse("tournaments:participants", kwargs={"slug": self.tournament.slug})).json()
        self.assertIn("19 очков", directory["html"])
        catalog = self.client.get(reverse("tournaments:index"))
        self.assertContains(catalog, "19 очков")

    def test_rules_freeze_after_first_publication(self):
        self.coupon()
        self.tournament.streak_bonus_points = 123
        with self.assertRaises(ValidationError):
            self.tournament.full_clean()


class TournamentPointsPublicationTests(PointsFixtures, TestCase):
    def test_daily_limit_and_idempotent_attachment(self):
        links = [self.coupon("pending", attach=True)[1] for _ in range(5)]
        self.assertEqual(attach_coupon_to_tournament(links[-1].coupon, self.tournament).pk, links[-1].pk)
        with self.assertRaisesMessage(ValidationError, "Лимит турнира — 5"):
            self.coupon("pending", attach=True)

    def test_cancellation_does_not_reopen_publication_slot(self):
        coupons = [self.coupon("pending", attach=True)[0] for _ in range(5)]
        cancel_published_coupon(coupons[0].pk)
        with self.assertRaisesMessage(ValidationError, "Лимит турнира — 5"):
            self.coupon("pending", attach=True)

    def test_next_local_day_reopens_limit(self):
        current = timezone.now()
        for _ in range(5):
            self.coupon("pending", attach=True)
        # Shift the entire tournament day, leaving the matches in the future.
        with patch("tournaments.services.coupons.timezone.now", return_value=current-timedelta(days=1)):
            self.coupon("pending", attach=True)

    def test_started_match_rejected_even_when_scope_is_stale(self):
        coupon, link = self.coupon("pending")
        link.delete()
        Match.objects.filter(pk=coupon.predictions.first().match_id).update(
            starts_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaisesMessage(ValidationError, "до начала матча"):
            attach_coupon_to_tournament(coupon, self.tournament)


@skipUnlessDBFeature("has_select_for_update")
class TournamentPointsConcurrencyTests(PointsFixtures, TransactionTestCase):
    def test_parallel_finalization_awards_once(self):
        self.coupon()
        TournamentPrize.objects.create(tournament=self.tournament, place=1, coins_amount=200)
        self.tournament.ends_at = timezone.now() - timedelta(seconds=1)
        self.tournament.save()
        barrier = Barrier(2)

        def finalize(_):
            close_old_connections()
            try:
                tournament = Tournament.objects.get(pk=self.tournament.pk)
                barrier.wait(timeout=10)
                try:
                    finalize_tournament_results(tournament)
                    return "finalized"
                except ValidationError:
                    return "already_finalized"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(finalize, range(2)))
        self.assertCountEqual(outcomes, ["finalized", "already_finalized"])
        self.assertEqual(self.tournament.prize_awards.count(), 1)
        self.participant.user.coin_wallet.refresh_from_db()
        self.assertEqual(self.participant.user.coin_wallet.balance, 1200)

    def test_parallel_publications_do_not_exceed_limit(self):
        self.tournament.daily_coupon_limit = 1
        self.tournament.save()
        coupon_ids = []
        for _ in range(2):
            coupon, link = self.coupon("pending")
            link.delete()
            coupon.published_status = "draft"
            coupon.save()
            coupon_ids.append(coupon.pk)
        barrier = Barrier(2)

        def publish(coupon_id):
            close_old_connections()
            try:
                coupon = PredictionCoupon.objects.get(pk=coupon_id)
                tournament = Tournament.objects.get(pk=self.tournament.pk)
                barrier.wait(timeout=10)
                try:
                    with transaction.atomic():
                        coupon.published_status = "published"
                        coupon.save()
                        attach_coupon_to_tournament(coupon, tournament)
                    return "published"
                except ValidationError:
                    return "limited"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(publish, coupon_ids))
        self.assertCountEqual(outcomes, ["published", "limited"])
        self.assertEqual(self.participant.tournament_coupons.count(), 1)
        self.assertEqual(PredictionCoupon.objects.filter(pk__in=coupon_ids, published_status="published").count(), 1)
