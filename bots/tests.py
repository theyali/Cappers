from decimal import Decimal
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bots.models import (
    BotAccount,
    BotExpertStrategy,
    BotOnlineSession,
    BotPlannedAction,
    BotRuntimeControl,
)
from bots.services import (
    _available_picks,
    _candidate_score,
    _express_probability,
    _like_prediction,
    _pick_is_reasonable,
    _target_coefficient,
    cleanup_bot_runtime_data,
    get_bot_runtime_status,
    preview_bot_predictions,
    preview_bot_tournament_activity,
    reset_stale_bot_planned_actions,
    run_bot_activity,
    run_bot_planned_actions,
    run_bot_presence_activity,
    run_bot_predictions,
    run_bot_tournament_activity,
    set_bot_runtime_mode,
)
from cabinet.models import User
from cabinet.presence import UserPresence
from front.models import PredictionLike
from game.models import Match, MatchOdds, Prediction, PredictionCoupon, Sport
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant


class BotPickSelectionTests(SimpleTestCase):
    def test_available_picks_skip_direct_zero_handicap(self):
        match = SimpleNamespace(
            home_team_name="Home U21",
            away_team_name="Away",
            odds=SimpleNamespace(
                home_win_bet=1.90,
                x_bet=3.30,
                away_win_bet=4.20,
                goals_over_2_5=1.85,
                goals_under_2_5=1.95,
                btts_yes=1.80,
                btts_no=2.00,
                d_1x=1.22,
                d_2x=1.74,
                fora_1_0=1.66,
                fora_2_0=2.24,
                totals_all={},
                double_chance_all={},
                btts_all={},
                handicaps_all={"Home U21 0": 1.66, "Home U21 -1.5": 2.35, "Away +1.5": 1.62},
            ),
        )

        selections = [pick.selection for pick in _available_picks(match)]

        self.assertNotIn("Home U21 фора 0", selections)
        self.assertNotIn("Away фора 0", selections)
        self.assertIn("Home U21 фора -1.5", selections)
        self.assertIn("Away фора +1.5", selections)

    def test_unrealistic_high_coefficient_is_rejected(self):
        strategy = SimpleNamespace(risk_profile=BotExpertStrategy.RiskProfile.BALANCED)
        match = SimpleNamespace(sport_code="football")
        pick = SimpleNamespace(market="total", selection="ТБ 6.5", coefficient=Decimal("21.00"))

        self.assertFalse(_pick_is_reasonable(match, pick, strategy))

    def test_safe_candidate_score_prefers_profile_coefficient_target(self):
        now = timezone.now()
        strategy = SimpleNamespace(
            risk_profile=BotExpertStrategy.RiskProfile.SAFE,
            bot_id=0,
        )
        match = SimpleNamespace(
            starts_at=now + timedelta(hours=4),
            sport_code="football",
            league_id=1,
            league_name="Premier League",
            league_name_en="Premier League",
        )
        target_pick = SimpleNamespace(market="winner", selection="Home", coefficient=Decimal("1.62"))
        high_pick = SimpleNamespace(market="winner", selection="Away", coefficient=Decimal("2.20"))

        self.assertGreater(
            _candidate_score(match, target_pick, strategy, now),
            _candidate_score(match, high_pick, strategy, now),
        )

    def test_late_aggressive_tournament_raises_target_coefficient(self):
        now = timezone.now()
        strategy = SimpleNamespace(risk_profile=BotExpertStrategy.RiskProfile.AGGRESSIVE)
        tournament = SimpleNamespace(
            starts_at=now - timedelta(days=3),
            ends_at=now + timedelta(hours=6),
        )

        self.assertEqual(
            _target_coefficient(strategy, tournament=tournament, now=now),
            Decimal("2.80"),
        )


class BotRuntimeTests(TestCase):
    def _analyst_bot(self, username: str) -> BotAccount:
        user = User.objects.create_user(
            username=username,
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        bot = BotAccount.objects.create(
            user=user,
            kind=BotAccount.Kind.EXPERT,
            persona=username,
            is_active=True,
        )
        BotExpertStrategy.objects.create(
            bot=bot,
            daily_predictions_min=1,
            daily_predictions_max=1,
            next_run_at=timezone.now() - timedelta(minutes=1),
        )
        return bot

    def test_run_bot_predictions_creates_unique_picks_without_comment_field(self):
        self._analyst_bot("bot_expert_one")
        self._analyst_bot("bot_expert_two")
        match = Match.objects.create(
            external_id=1001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(
            match=match,
            home_win_bet=1.91,
            x_bet=3.40,
            away_win_bet=4.10,
            goals_over_2_5=1.86,
            goals_under_2_5=1.94,
            btts_yes=1.82,
            btts_no=1.98,
            d_1x=1.28,
            d_2x=1.75,
            handicaps_all={"Home -1.5": 2.30, "Away +1.5": 1.61},
        )

        result = run_bot_predictions(execute_immediately=True)

        self.assertEqual(result["created"], 2)
        picks = set(Prediction.objects.values_list("match_id", "market", "selection"))
        self.assertEqual(len(picks), 2)
        self.assertFalse(any("фора 0" in selection for _, _, selection in picks))

    def test_run_bot_predictions_avoids_recent_identical_bot_pick(self):
        bot = self._analyst_bot("bot_expert_three")
        bot.expert_strategy.daily_predictions_max = 2
        bot.expert_strategy.save(update_fields=["daily_predictions_max"])
        match = Match.objects.create(
            external_id=1002,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(match=match, home_win_bet=1.80, away_win_bet=2.05)
        coupon = PredictionCoupon.objects.create(
            author=bot.user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("180.00"),
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="Home",
            coefficient=Decimal("1.80"),
            stake=Decimal("100.00"),
        )

        result = run_bot_predictions(execute_immediately=True)

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skip_reasons"], {"no_reasonable_pick": 1})

    def test_like_prediction_uses_coupon_id(self):
        reader = User.objects.create_user(username="reader_bot", password="safe-test-password")
        bot = BotAccount.objects.create(
            user=reader,
            kind=BotAccount.Kind.READER,
            persona="reader",
            is_active=True,
        )
        analyst = User.objects.create_user(
            username="human_analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        coupon = PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("180.00"),
            published_at=timezone.now(),
        )

        self.assertTrue(_like_prediction(bot))
        self.assertTrue(PredictionLike.objects.filter(prediction=coupon, user=reader).exists())
        self.assertEqual(PredictionLike.objects.count(), 1)

    @patch("bots.services._express_probability", return_value=1)
    def test_run_bot_predictions_can_create_express_coupon(self, _probability):
        self._analyst_bot("bot_express")
        now = timezone.now()
        for index in range(3):
            match = Match.objects.create(
                external_id=2000 + index,
                sync_scope=Match.SyncScope.PREMATCH,
                starts_at=now + timedelta(days=1, hours=index),
                raw_data={
                    "teams": {
                        "home": {"name": {"en": f"Home {index}"}},
                        "away": {"name": {"en": f"Away {index}"}},
                    }
                },
            )
            MatchOdds.objects.create(
                match=match,
                home_win_bet=Decimal("1.65"),
                away_win_bet=Decimal("2.10"),
                goals_over_2_5=Decimal("1.75"),
                goals_under_2_5=Decimal("1.95"),
            )

        result = run_bot_predictions(now=now, execute_immediately=True)

        self.assertEqual(result["created"], 1)
        coupon = PredictionCoupon.objects.get(author__username="bot_express")
        self.assertEqual(coupon.coupon_type, PredictionCoupon.CouponType.EXPRESS)
        self.assertGreaterEqual(coupon.predictions.count(), 2)

    @patch("bots.services.random.random", return_value=0)
    def test_tournament_activity_can_join_live_tournament(self, _random):
        self._analyst_bot("bot_tournament_join")
        tournament = Tournament.objects.create(
            title="Bot Cup Join",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=2),
        )

        result = run_bot_tournament_activity()

        self.assertEqual(result["joined"], 1)
        self.assertTrue(
            TournamentParticipant.objects.filter(
                tournament=tournament,
                user__username="bot_tournament_join",
                status=TournamentParticipant.Status.ACTIVE,
            ).exists()
        )

    def test_tournament_activity_creates_rare_tournament_coupon(self):
        sport = Sport.objects.create(
            external_id=3000,
            code="football",
            name="Football",
            name_ru="Футбол",
        )
        bot = self._analyst_bot("bot_tournament_coupon")
        bot.expert_strategy.daily_predictions_max = 2
        bot.expert_strategy.save(update_fields=["daily_predictions_max"])
        now = timezone.now()
        tournament = Tournament.objects.create(
            title="Bot Cup Coupon",
            status=Tournament.Status.PUBLISHED,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=2),
            min_coefficient=Decimal("1.50"),
            coupon_type_rule=Tournament.CouponTypeRule.SINGLE,
        )
        tournament.allowed_sports.add(sport)
        participant = TournamentParticipant.objects.create(
            tournament=tournament,
            user=bot.user,
        )
        TournamentParticipant.objects.filter(pk=participant.pk).update(
            joined_at=now - timedelta(hours=1)
        )
        match = Match.objects.create(
            external_id=3001,
            sport=sport,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(hours=3),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(
            match=match,
            home_win_bet=Decimal("1.70"),
            away_win_bet=Decimal("2.20"),
            goals_over_2_5=Decimal("1.90"),
        )

        result = run_bot_tournament_activity(now=now)

        self.assertEqual(result["created"], 1)
        tournament_coupon = TournamentCoupon.objects.get(tournament=tournament)
        self.assertEqual(tournament_coupon.coupon.author, bot.user)
        self.assertEqual(tournament_coupon.coupon.coupon_type, PredictionCoupon.CouponType.SINGLE)
        self.assertEqual(tournament_coupon.prediction_entries.count(), 1)

    def test_preview_bot_tournament_activity_shows_join_without_side_effects(self):
        self._analyst_bot("bot_tournament_preview_join")
        tournament = Tournament.objects.create(
            title="Bot Cup Preview Join",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=2),
        )

        result = preview_bot_tournament_activity(limit=3)

        self.assertEqual(result["tournaments"], 1)
        self.assertEqual(len(result["join_previews"]), 1)
        self.assertEqual(result["join_previews"][0]["tournament_id"], tournament.id)
        self.assertFalse(TournamentParticipant.objects.filter(tournament=tournament).exists())

    def test_preview_bot_tournament_activity_shows_coupon_without_side_effects(self):
        sport = Sport.objects.create(
            external_id=3500,
            code="football-preview",
            name="Football Preview",
            name_ru="Футбол Preview",
        )
        bot = self._analyst_bot("bot_tournament_preview_coupon")
        now = timezone.now()
        tournament = Tournament.objects.create(
            title="Bot Cup Preview Coupon",
            status=Tournament.Status.PUBLISHED,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=2),
            min_coefficient=Decimal("1.50"),
            coupon_type_rule=Tournament.CouponTypeRule.SINGLE,
        )
        tournament.allowed_sports.add(sport)
        participant = TournamentParticipant.objects.create(
            tournament=tournament,
            user=bot.user,
        )
        TournamentParticipant.objects.filter(pk=participant.pk).update(
            joined_at=now - timedelta(hours=1)
        )
        match = Match.objects.create(
            external_id=3501,
            sport=sport,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(hours=3),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(
            match=match,
            home_win_bet=Decimal("1.70"),
            away_win_bet=Decimal("2.20"),
        )

        result = preview_bot_tournament_activity(now=now, limit=3)

        self.assertEqual(len(result["coupon_previews"]), 1)
        self.assertEqual(result["coupon_previews"][0]["tournament_id"], tournament.id)
        self.assertEqual(result["coupon_previews"][0]["bot"], bot.user.username)
        self.assertEqual(PredictionCoupon.objects.filter(author=bot.user).count(), 0)
        self.assertEqual(TournamentCoupon.objects.filter(tournament=tournament).count(), 0)

    def test_repair_bot_predictions_cancels_bad_published_coupon_only_with_apply(self):
        bot = self._analyst_bot("bot_repair")
        match = Match.objects.create(
            external_id=4001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        coupon = PredictionCoupon.objects.create(
            author=bot.user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("2100.00"),
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="total",
            selection="ТБ 7.5",
            coefficient=Decimal("21.00"),
            stake=Decimal("100.00"),
        )

        call_command("repair_bot_predictions", stdout=StringIO())
        coupon.refresh_from_db()
        self.assertEqual(coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)

        call_command("repair_bot_predictions", "--apply", stdout=StringIO())
        coupon.refresh_from_db()
        self.assertEqual(coupon.published_status, PredictionCoupon.PublishedStatus.CANCELED)

    def test_inspect_bots_outputs_coefficient_buckets_and_queue_issues(self):
        bot = self._analyst_bot("bot_inspect")
        now = timezone.now()
        match = Match.objects.create(
            external_id=4401,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        coupon = PredictionCoupon.objects.create(
            author=bot.user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("210.00"),
            published_at=now,
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="Home",
            coefficient=Decimal("2.10"),
            stake=Decimal("100.00"),
        )
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.FAILED,
            scheduled_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=1),
            error="test failure",
        )

        output = StringIO()
        call_command("inspect_bots", "--hours", "24", stdout=output)
        text = output.getvalue()

        self.assertIn("КФ позиций:", text)
        self.assertIn("'2.00-2.99': 1", text)
        self.assertIn("КФ купонов:", text)
        self.assertIn("Последние проблемы очереди:", text)
        self.assertIn("test failure", text)

    def test_cleanup_bot_runtime_data_removes_old_done_skipped_and_sessions(self):
        bot = self._analyst_bot("bot_cleanup")
        now = timezone.now()
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.DONE,
            scheduled_at=now - timedelta(days=20),
            finished_at=now - timedelta(days=20),
        )
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.SKIPPED,
            scheduled_at=now - timedelta(days=20),
            finished_at=now - timedelta(days=20),
        )
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.FAILED,
            scheduled_at=now - timedelta(days=20),
            finished_at=now - timedelta(days=20),
        )
        BotOnlineSession.objects.create(
            bot=bot,
            starts_at=now - timedelta(days=20, minutes=20),
            ends_at=now - timedelta(days=20),
        )

        result = cleanup_bot_runtime_data(now=now, planned_days=14, sessions_days=14)

        self.assertEqual(result["planned_deleted"], 2)
        self.assertEqual(result["sessions_deleted"], 1)
        self.assertEqual(BotPlannedAction.objects.count(), 1)
        self.assertTrue(
            BotPlannedAction.objects.filter(status=BotPlannedAction.Status.FAILED).exists()
        )
        self.assertEqual(BotOnlineSession.objects.count(), 0)

    def test_reset_stale_bot_planned_actions_returns_running_to_pending(self):
        bot = self._analyst_bot("bot_reset_running")
        now = timezone.now()
        stale = BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.RUNNING,
            scheduled_at=now - timedelta(hours=1),
            started_at=now - timedelta(hours=1),
            error="worker stopped",
        )

        result = reset_stale_bot_planned_actions(now=now, older_minutes=30)

        self.assertEqual(result["reset"], 1)
        stale.refresh_from_db()
        self.assertEqual(stale.status, BotPlannedAction.Status.PENDING)
        self.assertIsNone(stale.started_at)
        self.assertEqual(stale.error, "")

    def test_runtime_mode_can_disable_bot_cycles(self):
        self._analyst_bot("bot_runtime_paused")
        set_bot_runtime_mode(BotRuntimeControl.Mode.PAUSED)

        prediction_result = run_bot_predictions()
        presence_result = run_bot_presence_activity()
        planned_result = run_bot_planned_actions()

        self.assertEqual(prediction_result["reason"], "bot_runtime_disabled")
        self.assertEqual(presence_result["reason"], "bot_runtime_disabled")
        self.assertEqual(planned_result["reason"], "bot_runtime_disabled")
        self.assertFalse(get_bot_runtime_status()["enabled"]["predictions"])

    def test_tournaments_only_runtime_leaves_reader_actions_pending(self):
        bot = self._analyst_bot("bot_runtime_tournaments")
        now = timezone.now()
        reader_action = BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.READER_ACTIVITY,
            scheduled_at=now - timedelta(minutes=1),
        )
        tournament_action = BotPlannedAction.objects.create(
            action=BotPlannedAction.Action.TOURNAMENT_ACTIVITY,
            scheduled_at=now - timedelta(minutes=1),
        )
        set_bot_runtime_mode(BotRuntimeControl.Mode.TOURNAMENTS_ONLY)

        result = run_bot_planned_actions(now=now)

        self.assertEqual(result["due"], 1)
        reader_action.refresh_from_db()
        tournament_action.refresh_from_db()
        self.assertEqual(reader_action.status, BotPlannedAction.Status.PENDING)
        self.assertEqual(tournament_action.status, BotPlannedAction.Status.SKIPPED)

    def test_control_bots_command_sets_runtime_mode(self):
        output = StringIO()

        call_command("control_bots", "--only-presence", stdout=output)

        control = BotRuntimeControl.load()
        self.assertEqual(control.mode, BotRuntimeControl.Mode.PRESENCE_ONLY)
        self.assertIn("presence", output.getvalue())

    def test_run_bot_predictions_plans_action_without_immediate_coupon(self):
        bot = self._analyst_bot("bot_queue_plan")

        result = run_bot_predictions(now=timezone.now())

        self.assertEqual(result["planned"], 1)
        self.assertEqual(PredictionCoupon.objects.filter(author=bot.user).count(), 0)
        action = BotPlannedAction.objects.get(bot=bot)
        self.assertEqual(action.action, BotPlannedAction.Action.PREDICTION)
        self.assertEqual(action.status, BotPlannedAction.Status.PENDING)
        self.assertGreater(action.scheduled_at, timezone.now())

    def test_preview_bot_predictions_has_no_side_effects(self):
        bot = self._analyst_bot("bot_preview")
        now = timezone.now()
        match = Match.objects.create(
            external_id=4501,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(
            match=match,
            home_win_bet=Decimal("1.78"),
            away_win_bet=Decimal("2.05"),
        )

        result = preview_bot_predictions(now=now)

        self.assertEqual(result["strategies"], 1)
        self.assertEqual(len(result["previews"]), 1)
        self.assertEqual(result["previews"][0]["bot"], bot.user.username)
        self.assertEqual(PredictionCoupon.objects.filter(author=bot.user).count(), 0)
        self.assertEqual(BotPlannedAction.objects.filter(bot=bot).count(), 0)

    def test_express_probability_recovers_when_bot_has_no_recent_express(self):
        bot = self._analyst_bot("bot_express_recovery")
        now = timezone.now()
        strategy = bot.expert_strategy

        without_recent = _express_probability(strategy, now=now)
        PredictionCoupon.objects.create(
            author=bot.user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            coupon_type=PredictionCoupon.CouponType.EXPRESS,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("240.00"),
            published_at=now,
        )

        with_recent = _express_probability(strategy, now=now)

        self.assertGreater(without_recent, with_recent)

    def test_run_bot_planned_actions_executes_due_prediction(self):
        bot = self._analyst_bot("bot_queue_execute")
        now = timezone.now()
        match = Match.objects.create(
            external_id=5001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(
            match=match,
            home_win_bet=Decimal("1.75"),
            away_win_bet=Decimal("2.10"),
        )
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            scheduled_at=now - timedelta(minutes=1),
            payload={"strategy_id": bot.expert_strategy.id},
        )

        result = run_bot_planned_actions(now=now)

        self.assertEqual(result["executed"], 1)
        self.assertEqual(PredictionCoupon.objects.filter(author=bot.user).count(), 1)
        action = BotPlannedAction.objects.get(bot=bot)
        self.assertEqual(action.status, BotPlannedAction.Status.DONE)

    def test_run_bot_activity_plans_reader_actions(self):
        user = User.objects.create_user(username="reader_queue", password="safe-test-password")
        bot = BotAccount.objects.create(
            user=user,
            kind=BotAccount.Kind.READER,
            persona="reader",
            is_active=True,
        )
        session = BotOnlineSession.objects.create(
            bot=bot,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(minutes=20),
            target_actions=2,
        )

        result = run_bot_activity(max_actions=5)

        self.assertEqual(result["planned"], 1)
        action = BotPlannedAction.objects.get(bot=bot)
        self.assertEqual(action.action, BotPlannedAction.Action.READER_ACTIVITY)
        self.assertEqual(action.status, BotPlannedAction.Status.PENDING)
        self.assertEqual(action.payload["session_id"], session.id)
        session.refresh_from_db()
        self.assertEqual(session.actions_planned, 1)

    @patch("bots.services.random.uniform", return_value=0.5)
    def test_run_bot_presence_activity_marks_some_bots_online_and_recent(self, _uniform):
        now = timezone.now()
        for index in range(4):
            self._analyst_bot(f"presence_bot_{index}")

        result = run_bot_presence_activity(now=now)

        self.assertEqual(result["online"], 2)
        self.assertEqual(result["recent"], 2)
        self.assertEqual(result["sessions_started"], 2)
        self.assertEqual(result["bots"], 4)
        self.assertEqual(BotOnlineSession.objects.count(), 2)
        last_seen_values = list(UserPresence.objects.values_list("last_seen_at", flat=True))
        self.assertEqual(len(last_seen_values), 4)
        self.assertEqual(sum(1 for value in last_seen_values if now - value <= timedelta(minutes=5)), 2)

    @patch("bots.services._like_prediction", return_value=True)
    @patch("bots.services.random.random", return_value=0)
    def test_bot_online_session_limits_social_actions_to_two(self, _random, _like_prediction):
        now = timezone.now()
        bot = self._analyst_bot("session_action_limit_bot")
        session = BotOnlineSession.objects.create(
            bot=bot,
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(minutes=30),
            target_actions=2,
        )

        first_result = run_bot_activity(max_actions=5)
        BotPlannedAction.objects.filter(bot=bot).update(scheduled_at=now - timedelta(seconds=1))
        first_execute = run_bot_planned_actions(now=now)
        second_result = run_bot_activity(max_actions=5)
        BotPlannedAction.objects.filter(bot=bot, status=BotPlannedAction.Status.PENDING).update(
            scheduled_at=now + timedelta(minutes=1)
        )
        second_execute = run_bot_planned_actions(now=now + timedelta(minutes=2))
        third_result = run_bot_activity(max_actions=5)

        self.assertEqual(first_result["planned"], 1)
        self.assertEqual(first_execute["executed"], 1)
        self.assertEqual(second_result["planned"], 1)
        self.assertEqual(second_execute["executed"], 1)
        self.assertEqual(third_result["planned"], 0)
        session.refresh_from_db()
        self.assertEqual(session.actions_planned, 2)
        self.assertEqual(session.actions_done, 2)

    def test_social_action_without_active_session_is_skipped(self):
        bot = self._analyst_bot("session_required_bot")
        now = timezone.now()
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.READER_ACTIVITY,
            scheduled_at=now - timedelta(minutes=1),
        )

        result = run_bot_planned_actions(now=now)

        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["reasons"], {"no_active_session": 1})
