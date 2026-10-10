import json
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from cabinet.models import AnalystFollow, User, UserVipSubscription
from front.models import PredictionLike
from game.models import Match, MatchOdds, Prediction, PredictionCoupon, Sport
from tournaments import views
from tournaments.services.coupons import create_tournament_coupon
from tournaments.services.eligibility import check_tournament_eligibility
from tournaments.services.join import TournamentJoinError, join_tournament
from tournaments.services.leaderboard import finalize_tournament_results, tournament_leaderboard
from tournaments.services.rewards import award_tournament_prizes
from tournaments.services.rules import TournamentRuleError, validate_tournament_coupon

from .models import (
    Tournament,
    TournamentAchievement,
    TournamentCoupon,
    TournamentEligibilityRule,
    TournamentParticipant,
    TournamentPredictionEntry,
    TournamentPrize,
    TournamentPrizeAward,
    TournamentResult,
)
from wallets.models import CoinTransaction, RealBalanceTransaction
from wallets.services import ensure_coin_wallet


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class TournamentPredictionEntryTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="tournament-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.tournament = Tournament.objects.create(
            title="September Profit Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=7),
            prize_first=Decimal("1000.00"),
            prize_second=Decimal("500.00"),
            prize_third=Decimal("250.00"),
        )
        self.participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.match = Match.objects.create(
            external_id=770001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=3),
        )

    def _tournament_prediction_entry(self, selection: str) -> TournamentPredictionEntry:
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        prediction = Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection=selection,
            coefficient=Decimal("2.00"),
            stake=Decimal("100.00"),
        )
        tournament_coupon = TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=self.participant,
            coupon=coupon,
        )
        return TournamentPredictionEntry.objects.create(
            tournament=self.tournament,
            participant=self.participant,
            tournament_coupon=tournament_coupon,
            prediction=prediction,
            match=self.match,
        )

    def test_participant_can_use_match_only_once_per_tournament(self):
        self._tournament_prediction_entry("Хозяева")

        with self.assertRaises(IntegrityError):
            self._tournament_prediction_entry("Гости")


class TournamentServiceTests(TestCase):
    def setUp(self):
        self.football = Sport.objects.create(
            external_id=1001,
            code="football",
            name="Football",
            name_ru="Футбол",
        )
        self.basketball = Sport.objects.create(
            external_id=1002,
            code="basketball",
            name="Basketball",
            name_ru="Баскетбол",
        )
        self.analyst = User.objects.create_user(
            username="rules-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(
            username="rules-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.tournament = Tournament.objects.create(
            title="Rules Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=3),
            prize_first=Decimal("1000.00"),
            prize_second=Decimal("500.00"),
            prize_third=Decimal("250.00"),
            min_coefficient=Decimal("2.00"),
            min_confidence=90,
            coupon_type_rule=Tournament.CouponTypeRule.SINGLE,
        )
        self.tournament.allowed_sports.add(self.football)
        self.participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.football_match = Match.objects.create(
            external_id=880001,
            sport=self.football,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=3),
        )
        self.basketball_match = Match.objects.create(
            external_id=880002,
            sport=self.basketball,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=4),
        )
        MatchOdds.objects.create(match=self.football_match, home_win_bet=2.00)
        MatchOdds.objects.create(match=self.basketball_match, home_win_bet=2.00)

    def _item(self, match=None, coefficient=Decimal("2.00")):
        return {
            "match": match or self.football_match,
            "market": "winner",
            "selection": "Хозяева",
            "coefficient": coefficient,
        }

    def _payload(self, match=None, coefficient="2.00", confidence=95, stake="100"):
        match = match or self.football_match
        return {
            "stake": stake,
            "confidence": confidence,
            "items": [
                {
                    "match_id": match.id,
                    "market": "winner",
                    "selection": "Хозяева",
                    "coefficient": coefficient,
                }
            ],
        }

    def test_join_tournament_allows_only_analysts(self):
        self.tournament.starts_at = timezone.now() + timedelta(days=1)
        self.tournament.ends_at = timezone.now() + timedelta(days=3)
        self.tournament.save(update_fields=("starts_at", "ends_at", "updated_at"))

        with self.assertRaises(TournamentJoinError):
            join_tournament(self.reader, self.tournament)

        participant = join_tournament(self.analyst, self.tournament)

        self.assertEqual(participant.status, TournamentParticipant.Status.ACTIVE)

    def test_rules_validate_min_coefficient_confidence_sport_and_type(self):
        with self.assertRaisesMessage(TournamentRuleError, "Минимальная уверенность"):
            validate_tournament_coupon(
                self.tournament,
                self.participant,
                confidence=80,
                items=[self._item()],
            )

        with self.assertRaisesMessage(TournamentRuleError, "Минимальный коэффициент"):
            validate_tournament_coupon(
                self.tournament,
                self.participant,
                confidence=95,
                items=[self._item(coefficient=Decimal("1.90"))],
            )

        with self.assertRaisesMessage(TournamentRuleError, "Баскетбол"):
            validate_tournament_coupon(
                self.tournament,
                self.participant,
                confidence=95,
                items=[self._item(match=self.basketball_match)],
            )

        with self.assertRaisesMessage(TournamentRuleError, "только одиночные"):
            validate_tournament_coupon(
                self.tournament,
                self.participant,
                confidence=95,
                items=[self._item(), self._item(match=self.basketball_match)],
            )

    def test_create_tournament_coupon_creates_public_coupon_and_tournament_links(self):
        coupon, tournament_coupon = create_tournament_coupon(
            user=self.analyst,
            tournament=self.tournament,
            payload=self._payload(),
        )

        self.assertEqual(coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(coupon.coupon_type, PredictionCoupon.CouponType.SINGLE)
        self.assertEqual(coupon.audience, PredictionCoupon.Audience.FREE)
        self.assertEqual(tournament_coupon.tournament, self.tournament)
        self.assertEqual(tournament_coupon.participant, self.participant)
        self.assertEqual(TournamentPredictionEntry.objects.filter(tournament=self.tournament).count(), 1)
        self.analyst.coin_wallet.refresh_from_db()
        self.assertEqual(self.analyst.coin_wallet.balance, 900)

    def test_create_tournament_coupon_rejects_second_prediction_for_same_match(self):
        create_tournament_coupon(
            user=self.analyst,
            tournament=self.tournament,
            payload=self._payload(),
        )

        with self.assertRaisesMessage(ValidationError, "один матч"):
            create_tournament_coupon(
                user=self.analyst,
                tournament=self.tournament,
                payload=self._payload(match=self.football_match),
            )

    def test_leaderboard_and_finalization_calculate_places(self):
        second = User.objects.create_user(
            username="second-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        second_participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=second,
        )
        first_coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("300.00"),
            confidence=95,
            published_at=timezone.now(),
        )
        second_coupon = PredictionCoupon.objects.create(
            author=second,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.LOSE,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("250.00"),
            confidence=95,
            published_at=timezone.now(),
        )
        TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=self.participant,
            coupon=first_coupon,
        )
        TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=second_participant,
            coupon=second_coupon,
        )

        rows = tournament_leaderboard(self.tournament)

        self.assertEqual(rows[0]["participant"], self.participant)
        self.assertEqual(rows[0]["profit"], Decimal("200.00"))
        self.assertEqual(rows[0]["roi_percent"], Decimal("200.00"))
        self.assertEqual(rows[1]["participant"], second_participant)
        self.assertEqual(rows[1]["profit"], Decimal("-100.00"))

        self.tournament.ends_at = timezone.now() - timedelta(minutes=1)
        self.tournament.save(update_fields=("ends_at", "updated_at"))
        coin_transactions_before = CoinTransaction.objects.count()
        results = finalize_tournament_results(self.tournament)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].participant, self.participant)
        self.assertEqual(results[0].rank, 1)
        self.assertEqual(results[0].prize_amount, Decimal("1000.00"))
        self.analyst.real_balance.refresh_from_db()
        self.assertEqual(self.analyst.real_balance.balance, Decimal("1000.00"))
        self.assertTrue(
            RealBalanceTransaction.objects.filter(
                user=self.analyst,
                kind=RealBalanceTransaction.Kind.TOURNAMENT_PRIZE,
                amount=Decimal("1000.00"),
                related_model=self.tournament._meta.label_lower,
                related_id=self.tournament.pk,
            ).exists()
        )
        self.assertEqual(CoinTransaction.objects.count(), coin_transactions_before)

        with self.assertRaisesMessage(ValidationError, "уже зафиксированы"):
            finalize_tournament_results(self.tournament)
        self.analyst.real_balance.refresh_from_db()
        self.assertEqual(self.analyst.real_balance.balance, Decimal("1000.00"))

        self.client.force_login(self.analyst)
        earnings_page = self.client.get(reverse("cabinet:profile"), {"tab": "earnings"})
        self.assertContains(earnings_page, "Турниры")
        self.assertContains(earnings_page, "1 000 ₽")

    def test_finalization_awards_configured_prize_once(self):
        achievement = TournamentAchievement.objects.create(
            tournament=self.tournament,
            title="Победитель турнира",
            kind=TournamentAchievement.Kind.FIRST_PLACE,
        )
        prize = TournamentPrize.objects.create(
            tournament=self.tournament,
            place=1,
            money_amount=Decimal("1500.00"),
            coins_amount=700,
            vip_days=5,
            achievement=achievement,
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("300.00"),
            confidence=95,
            published_at=timezone.now(),
        )
        TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=self.participant,
            coupon=coupon,
        )
        self.tournament.ends_at = timezone.now() - timedelta(minutes=1)
        self.tournament.save(update_fields=("ends_at", "updated_at"))

        results = finalize_tournament_results(self.tournament)

        self.assertEqual(results[0].prize_amount, Decimal("1500.00"))
        self.assertEqual(results[0].achievement, achievement)
        award = TournamentPrizeAward.objects.get(tournament=self.tournament, participant=self.participant)
        self.assertEqual(award.prize, prize)
        self.assertEqual(award.money_awarded, Decimal("1500.00"))
        self.assertEqual(award.coins_awarded, 700)
        self.assertEqual(award.vip_days_awarded, 5)
        self.assertEqual(award.achievement_awarded, achievement)
        self.analyst.real_balance.refresh_from_db()
        self.assertEqual(self.analyst.real_balance.balance, Decimal("1500.00"))
        self.analyst.coin_wallet.refresh_from_db()
        self.assertEqual(self.analyst.coin_wallet.balance, 1700)
        self.assertTrue(
            CoinTransaction.objects.filter(
                user=self.analyst,
                kind=CoinTransaction.Kind.TOURNAMENT_PRIZE_COINS,
                amount=700,
            ).exists()
        )
        self.assertTrue(
            UserVipSubscription.objects.filter(
                user=self.analyst,
                source=UserVipSubscription.Source.TOURNAMENT,
                duration_days=5,
            ).exists()
        )

        with self.assertRaisesMessage(ValidationError, "уже зафиксированы"):
            finalize_tournament_results(self.tournament)
        self.analyst.real_balance.refresh_from_db()
        self.analyst.coin_wallet.refresh_from_db()
        self.assertEqual(TournamentPrizeAward.objects.filter(tournament=self.tournament).count(), 1)
        self.assertEqual(self.analyst.real_balance.balance, Decimal("1500.00"))
        self.assertEqual(self.analyst.coin_wallet.balance, 1700)
        self.assertEqual(
            UserVipSubscription.objects.filter(
                user=self.analyst,
                source=UserVipSubscription.Source.TOURNAMENT,
            ).count(),
            1,
        )


class TournamentAccessRewardTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(
            external_id=6101,
            code="hockey",
            name="Hockey",
            name_ru="Хоккей",
        )
        self.analyst = self._user("access-capper")

    def _user(self, username, *, role=User.Role.ANALYST, days_old=None):
        user = User.objects.create_user(
            username=username,
            password="safe-test-password",
            role=role,
        )
        if days_old is not None:
            User.objects.filter(pk=user.pk).update(
                date_joined=timezone.now() - timedelta(days=days_old),
            )
            user.refresh_from_db()
        return user

    def _tournament(self, title, **kwargs):
        defaults = {
            "title": title,
            "status": Tournament.Status.PUBLISHED,
            "starts_at": timezone.now() + timedelta(days=1),
            "ends_at": timezone.now() + timedelta(days=3),
            "min_coefficient": Decimal("1.20"),
        }
        defaults.update(kwargs)
        return Tournament.objects.create(**defaults)

    def _ended_tournament_with_result(self, prize_kwargs=None):
        tournament = self._tournament(
            f"Reward Cup {Tournament.objects.count()}",
            starts_at=timezone.now() - timedelta(days=3),
            ends_at=timezone.now() - timedelta(minutes=1),
        )
        participant = TournamentParticipant.objects.create(
            tournament=tournament,
            user=self.analyst,
        )
        result = TournamentResult.objects.create(
            tournament=tournament,
            participant=participant,
            rank=1,
            prize_amount=Decimal("0.00"),
            profit=Decimal("100.00"),
            roi_percent=Decimal("100.00"),
        )
        prize_defaults = {"place": 1, "money_amount": Decimal("0.00")}
        prize_defaults.update(prize_kwargs or {})
        prize = TournamentPrize.objects.create(tournament=tournament, **prize_defaults)
        return tournament, participant, result, prize

    def _coupon_for_likes(self, author):
        return PredictionCoupon.objects.create(
            author=author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=80,
            published_at=timezone.now(),
        )

    def test_open_free_tournament_allows_analyst(self):
        tournament = self._tournament("Open Free Cup")

        participant = join_tournament(self.analyst, tournament)

        self.assertEqual(participant.user, self.analyst)
        self.assertEqual(participant.status, TournamentParticipant.Status.ACTIVE)

    def test_closed_vip_only_tournament_requires_active_vip(self):
        tournament = self._tournament(
            "Closed VIP Cup",
            access_type=Tournament.AccessType.CLOSED,
            vip_only=True,
        )

        with self.assertRaisesMessage(TournamentJoinError, "VIP"):
            join_tournament(self.analyst, tournament)

        UserVipSubscription.objects.create(
            user=self.analyst,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(days=5),
            duration_days=5,
            source=UserVipSubscription.Source.ADMIN,
        )

        self.assertEqual(join_tournament(self.analyst, tournament).tournament, tournament)

    def test_new_users_only_tournament_rejects_old_user(self):
        tournament = self._tournament("New Users Cup", new_users_only=True)
        old_user = self._user("old-capper", days_old=60)

        with self.assertRaisesMessage(TournamentJoinError, "новым пользователям"):
            join_tournament(old_user, tournament)

        self.assertEqual(join_tournament(self.analyst, tournament).user, self.analyst)

    def test_tournament_winners_rule(self):
        tournament = self._tournament("Winners Only Cup")
        TournamentEligibilityRule.objects.create(
            tournament=tournament,
            rule_type=TournamentEligibilityRule.RuleType.TOURNAMENT_WINS,
            value=1,
        )

        with self.assertRaisesMessage(TournamentJoinError, "Победы в турнирах"):
            join_tournament(self.analyst, tournament)

        previous = self._tournament("Previous Cup", ends_at=timezone.now() - timedelta(days=1))
        previous_participant = TournamentParticipant.objects.create(
            tournament=previous,
            user=self.analyst,
        )
        TournamentResult.objects.create(
            tournament=previous,
            participant=previous_participant,
            rank=1,
        )

        self.assertEqual(join_tournament(self.analyst, tournament).user, self.analyst)

    def test_followers_rule(self):
        tournament = self._tournament("Followers Cup")
        TournamentEligibilityRule.objects.create(
            tournament=tournament,
            rule_type=TournamentEligibilityRule.RuleType.FOLLOWERS_COUNT,
            value=2,
        )
        AnalystFollow.objects.create(follower=self._user("follower-1", role=User.Role.READER), analyst=self.analyst)

        with self.assertRaisesMessage(TournamentJoinError, "не хватает 1"):
            join_tournament(self.analyst, tournament)

        AnalystFollow.objects.create(follower=self._user("follower-2", role=User.Role.READER), analyst=self.analyst)

        self.assertEqual(join_tournament(self.analyst, tournament).user, self.analyst)

    def test_likes_rule(self):
        tournament = self._tournament("Likes Cup")
        coupon = self._coupon_for_likes(self.analyst)
        TournamentEligibilityRule.objects.create(
            tournament=tournament,
            rule_type=TournamentEligibilityRule.RuleType.LIKES_COUNT,
            value=2,
        )
        PredictionLike.objects.create(prediction=coupon, user=self._user("like-1", role=User.Role.READER))

        with self.assertRaisesMessage(TournamentJoinError, "не хватает 1"):
            join_tournament(self.analyst, tournament)

        PredictionLike.objects.create(prediction=coupon, user=self._user("like-2", role=User.Role.READER))

        self.assertEqual(join_tournament(self.analyst, tournament).user, self.analyst)

    def test_combo_followers_and_likes_requires_both_rules(self):
        tournament = self._tournament("Combo Cup")
        TournamentEligibilityRule.objects.create(
            tournament=tournament,
            rule_type=TournamentEligibilityRule.RuleType.FOLLOWERS_COUNT,
            value=50,
            sort_order=1,
        )
        TournamentEligibilityRule.objects.create(
            tournament=tournament,
            rule_type=TournamentEligibilityRule.RuleType.LIKES_COUNT,
            value=200,
            sort_order=2,
        )
        users = [
            User(username=f"combo-user-{index}", role=User.Role.READER)
            for index in range(200)
        ]
        User.objects.bulk_create(users)
        users = list(User.objects.filter(username__startswith="combo-user-").order_by("id"))
        AnalystFollow.objects.bulk_create(
            AnalystFollow(follower=user, analyst=self.analyst)
            for user in users[:50]
        )
        coupon = self._coupon_for_likes(self.analyst)
        PredictionLike.objects.bulk_create(
            PredictionLike(prediction=coupon, user=user)
            for user in users[:199]
        )

        eligibility = check_tournament_eligibility(self.analyst, tournament)
        self.assertFalse(eligibility["allowed"])
        self.assertIn("не хватает 1", eligibility["reasons"][0])

        PredictionLike.objects.create(prediction=coupon, user=users[199])

        self.assertTrue(check_tournament_eligibility(self.analyst, tournament)["allowed"])

    def test_paid_tournament_charges_coins(self):
        tournament = self._tournament(
            "Paid Cup",
            entry_type=Tournament.EntryType.PAID,
            entry_fee_coins=300,
        )

        join_tournament(self.analyst, tournament)

        self.analyst.coin_wallet.refresh_from_db()
        self.assertEqual(self.analyst.coin_wallet.balance, 700)
        self.assertTrue(
            CoinTransaction.objects.filter(
                user=self.analyst,
                kind=CoinTransaction.Kind.TOURNAMENT_ENTRY_FEE,
                amount=-300,
            ).exists()
        )

    def test_paid_tournament_rejects_when_coins_are_not_enough(self):
        tournament = self._tournament(
            "Expensive Cup",
            entry_type=Tournament.EntryType.PAID,
            entry_fee_coins=500,
        )
        wallet = ensure_coin_wallet(self.analyst)
        wallet.balance = 100
        wallet.save(update_fields=("balance", "updated_at"))

        with self.assertRaisesMessage(TournamentJoinError, "Недостаточно коинов"):
            join_tournament(self.analyst, tournament)

        self.assertFalse(TournamentParticipant.objects.filter(tournament=tournament, user=self.analyst).exists())

    def test_awards_money(self):
        tournament, participant, result, prize = self._ended_tournament_with_result(
            {"money_amount": Decimal("1500.00")}
        )

        award_tournament_prizes(tournament, results=[result])

        self.analyst.real_balance.refresh_from_db()
        self.assertEqual(self.analyst.real_balance.balance, Decimal("1500.00"))
        self.assertEqual(TournamentPrizeAward.objects.get(participant=participant).prize, prize)

    def test_awards_coins(self):
        tournament, participant, result, prize = self._ended_tournament_with_result({"coins_amount": 400})

        award_tournament_prizes(tournament, results=[result])

        self.analyst.coin_wallet.refresh_from_db()
        self.assertEqual(self.analyst.coin_wallet.balance, 1400)
        self.assertEqual(TournamentPrizeAward.objects.get(participant=participant).coins_awarded, 400)

    def test_awards_vip(self):
        tournament, participant, result, prize = self._ended_tournament_with_result({"vip_days": 10})

        award_tournament_prizes(tournament, results=[result])

        self.assertTrue(
            UserVipSubscription.objects.filter(
                user=self.analyst,
                source=UserVipSubscription.Source.TOURNAMENT,
                duration_days=10,
            ).exists()
        )

    def test_awards_achievement(self):
        tournament, participant, result, prize = self._ended_tournament_with_result()
        achievement = TournamentAchievement.objects.create(
            tournament=tournament,
            title="First Place",
            kind=TournamentAchievement.Kind.FIRST_PLACE,
        )
        prize.achievement = achievement
        prize.save(update_fields=("achievement", "updated_at"))

        award_tournament_prizes(tournament, results=[result])

        result.refresh_from_db()
        self.assertEqual(result.achievement, achievement)
        self.assertEqual(TournamentPrizeAward.objects.get(participant=participant).achievement_awarded, achievement)

    def test_awards_are_not_applied_twice(self):
        tournament, participant, result, prize = self._ended_tournament_with_result(
            {"money_amount": Decimal("500.00"), "coins_amount": 200, "vip_days": 3}
        )

        award_tournament_prizes(tournament, results=[result])
        award_tournament_prizes(tournament, results=[result])

        self.analyst.real_balance.refresh_from_db()
        self.analyst.coin_wallet.refresh_from_db()
        self.assertEqual(TournamentPrizeAward.objects.filter(tournament=tournament, participant=participant).count(), 1)
        self.assertEqual(self.analyst.real_balance.balance, Decimal("500.00"))
        self.assertEqual(self.analyst.coin_wallet.balance, 1200)
        self.assertEqual(
            UserVipSubscription.objects.filter(user=self.analyst, source=UserVipSubscription.Source.TOURNAMENT).count(),
            1,
        )


class TournamentCouponEndpointTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="endpoint-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(
            username="endpoint-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.tournament = Tournament.objects.create(
            title="Endpoint Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=3),
            min_coefficient=Decimal("1.50"),
            min_confidence=70,
        )
        self.participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.match = Match.objects.create(
            external_id=990001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=3),
        )
        MatchOdds.objects.create(match=self.match, home_win_bet=1.80)

    def _payload(self):
        return {
            "stake": "200",
            "confidence": 75,
            "items": [
                {
                    "match_id": self.match.id,
                    "market": "winner",
                    "selection": "Хозяева",
                    "coefficient": "1.80",
                }
            ],
        }

    def test_create_coupon_route_uses_tournament_view(self):
        match = resolve(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug})
        )

        self.assertIs(match.func, views.create_coupon)

    def test_endpoint_creates_public_coupon_and_returns_balance(self):
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug}),
            data=json.dumps(self._payload()),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["message"], "Прогноз турнира опубликован.")
        self.assertEqual(payload["balance"], "9800.00")
        self.assertEqual(PredictionCoupon.objects.count(), 1)
        coupon = PredictionCoupon.objects.get()
        self.assertEqual(coupon.tournament_link.tournament, self.tournament)
        self.assertEqual(coupon.predictions.count(), 1)

    def test_endpoint_rejects_tampered_coefficient_with_current_odds(self):
        self.client.force_login(self.analyst)
        payload = self._payload()
        payload["items"][0]["coefficient"] = "25.00"

        response = self.client.post(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug}),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["odds_changed"][0]["coefficient"], "1.80")
        self.assertFalse(PredictionCoupon.objects.exists())

    def test_endpoint_checks_min_coefficient_against_line(self):
        self.tournament.min_coefficient = Decimal("2.00")
        self.tournament.save(update_fields=("min_coefficient", "updated_at"))
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug}),
            data=json.dumps(self._payload()),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Минимальный коэффициент", response.json()["error"])
        self.assertFalse(PredictionCoupon.objects.exists())

    def test_endpoint_rejects_user_without_participation(self):
        other = User.objects.create_user(
            username="outside-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(other)

        response = self.client.post(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug}),
            data=json.dumps(self._payload()),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Подключитесь к турниру", response.json()["error"])
        self.assertFalse(PredictionCoupon.objects.exists())

    def test_endpoint_rejects_reader(self):
        self.client.force_login(self.reader)

        response = self.client.post(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug}),
            data=json.dumps(self._payload()),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("капперы", response.json()["error"])

    def test_endpoint_rejects_invalid_json(self):
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug}),
            data="{bad json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Некорректный JSON.")


@override_settings(STORAGES=TEST_STORAGES)
class TournamentPageTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="page-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.tournament = Tournament.objects.create(
            title="Page Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=3),
            prize_first=Decimal("1000.00"),
            prize_second=Decimal("500.00"),
            prize_third=Decimal("250.00"),
        )
        self.match = Match.objects.create(
            external_id=991001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=4),
        )
        MatchOdds.objects.create(
            match=self.match,
            home_win_bet=2.2,
            x_bet=3.1,
            away_win_bet=2.8,
        )

    def _predict_url(self):
        selected_date = timezone.localtime(self.match.starts_at).date().isoformat()
        return (
            reverse("tournaments:predict", kwargs={"slug": self.tournament.slug})
            + f"?date={selected_date}"
        )

    def test_index_lists_published_tournament_cards(self):
        Tournament.objects.create(
            title="Hidden Cup",
            status=Tournament.Status.DRAFT,
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=1),
        )

        response = self.client.get(reverse("tournaments:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page Cup")
        self.assertContains(response, "Открыть турнир")
        self.assertNotContains(response, "Hidden Cup")

    def test_detail_shows_tournament_state_and_join_action_for_analyst(self):
        self.tournament.starts_at = timezone.now() + timedelta(days=1)
        self.tournament.ends_at = timezone.now() + timedelta(days=3)
        self.tournament.save(update_fields=("starts_at", "ends_at", "updated_at"))
        self.client.force_login(self.analyst)

        response = self.client.get(
            reverse("tournaments:detail", kwargs={"slug": self.tournament.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page Cup")
        self.assertContains(response, "Принять участие")
        self.assertContains(response, "Таблица турнира")
        self.assertContains(response, "Прогнозы турнира")

    def test_detail_hides_join_action_after_registration_closed(self):
        self.client.force_login(self.analyst)

        response = self.client.get(
            reverse("tournaments:detail", kwargs={"slug": self.tournament.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Принять участие")
        self.assertContains(response, "Регистрация на турнир завершена")

    def test_detail_links_joined_participant_to_tournament_prediction_page(self):
        TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.client.force_login(self.analyst)

        response = self.client.get(
            reverse("tournaments:detail", kwargs={"slug": self.tournament.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("tournaments:predict", kwargs={"slug": self.tournament.slug}),
        )
        self.assertContains(response, "Сделать прогноз")

    def test_predict_redirects_without_active_participation(self):
        self.client.force_login(self.analyst)

        response = self.client.get(self._predict_url())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.tournament.get_absolute_url())

    def test_predict_redirects_when_tournament_is_not_live(self):
        self.tournament.starts_at = timezone.now() + timedelta(days=1)
        self.tournament.ends_at = timezone.now() + timedelta(days=2)
        self.tournament.save(update_fields=("starts_at", "ends_at", "updated_at"))
        TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.client.force_login(self.analyst)

        response = self.client.get(self._predict_url())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.tournament.get_absolute_url())

    def test_predict_page_reuses_match_list_and_coupon_for_active_participant(self):
        TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.client.force_login(self.analyst)

        response = self.client.get(self._predict_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page Cup: прогноз")
        self.assertContains(
            response,
            f'data-create-url="{reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug})}"',
        )
        self.assertContains(response, 'data-autosave="false"')
        self.assertContains(response, 'data-bet-option data-bet-key="winner-home"')

    def test_predict_page_locks_match_already_used_in_tournament(self):
        participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("220.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        prediction = Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.20"),
            stake=Decimal("100.00"),
        )
        tournament_coupon = TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=participant,
            coupon=coupon,
        )
        TournamentPredictionEntry.objects.create(
            tournament=self.tournament,
            participant=participant,
            tournament_coupon=tournament_coupon,
            prediction=prediction,
            match=self.match,
        )
        self.client.force_login(self.analyst)

        response = self.client.get(self._predict_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Матч уже использован в турнире")
        self.assertNotContains(response, 'data-bet-option data-bet-key="winner-home"')

    def test_join_view_adds_active_participant(self):
        self.tournament.starts_at = timezone.now() + timedelta(days=1)
        self.tournament.ends_at = timezone.now() + timedelta(days=3)
        self.tournament.save(update_fields=("starts_at", "ends_at", "updated_at"))
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("tournaments:join", kwargs={"slug": self.tournament.slug}),
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            TournamentParticipant.objects.filter(
                tournament=self.tournament,
                user=self.analyst,
                status=TournamentParticipant.Status.ACTIVE,
            ).exists()
        )

    def test_detail_shows_tournament_predictions(self):
        participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("220.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        prediction = Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.20"),
            stake=Decimal("100.00"),
        )
        tournament_coupon = TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=participant,
            coupon=coupon,
        )
        TournamentPredictionEntry.objects.create(
            tournament=self.tournament,
            participant=participant,
            tournament_coupon=tournament_coupon,
            prediction=prediction,
            match=self.match,
        )

        response = self.client.get(
            reverse("tournaments:detail", kwargs={"slug": self.tournament.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Хозяева")
        self.assertContains(response, "page-capper")
        self.assertContains(response, 'data-prediction-card="')


class TournamentCatalogCardTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            title="Экспресс-челлендж",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=2),
            sponsor_name="COLDBET",
            sponsor_url="https://example.com/sponsor/",
            card_icon_bg_color="#0F7A43",
        )

    def test_card_shows_sponsor_and_custom_icon_color(self):
        response = self.client.get(reverse("tournaments:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-tournament-icon-color="#0F7A43"')
        self.assertContains(response, 'href="https://example.com/sponsor/"')
        self.assertContains(response, 'rel="sponsored noopener noreferrer"')
        self.assertContains(response, "COLDBET")
        self.assertContains(response, "Призовой фонд")
        self.assertContains(response, "Участвовать")
        self.assertContains(response, 'class="tournament-card tournament-card-live is-no-cover"')

    def test_joined_participant_changes_button_without_extra_queries_per_card(self):
        analyst = User.objects.create_user(
            username="tournament-card-member",
            password="secret",
            role=User.Role.ANALYST,
        )
        TournamentParticipant.objects.create(tournament=self.tournament, user=analyst)
        self.client.force_login(analyst)
        response = self.client.get(reverse("tournaments:index"))
        self.assertContains(response, "Вы в турнире")

    def test_card_color_requires_hex(self):
        self.tournament.card_icon_bg_color = "javascript:alert(1)"
        with self.assertRaises(ValidationError):
            self.tournament.full_clean()


    def test_multi_sport_card_does_not_show_only_first_sport(self):
        basketball = Sport.objects.create(
            code="basketball", name="Basketball", name_ru="Баскетбол",
        )
        hockey = Sport.objects.create(
            code="hockey", name="Hockey", name_ru="Хоккей",
        )
        self.tournament.allowed_sports.add(basketball, hockey)

        response = self.client.get(reverse("tournaments:index"))

        self.assertContains(response, "<small>Несколько видов спорта</small>")
        self.assertNotContains(response, "<small>Баскетбол</small>")

    def test_open_all_sports_tournament_title_is_not_labeled_basketball(self):
        basketball = Sport.objects.create(
            code="basketball", name="Basketball", name_ru="Баскетбол",
        )
        self.tournament.title = "Открытый Турнир по всем видам спорта"
        self.tournament.save(update_fields=["title"])
        self.tournament.allowed_sports.add(basketball)

        response = self.client.get(reverse("tournaments:index"))

        self.assertContains(response, "<small>Все виды спорта</small>")
        self.assertNotContains(response, "<small>Баскетбол</small>")

    def test_single_sport_tournament_keeps_its_sport(self):
        basketball = Sport.objects.create(
            code="basketball", name="Basketball", name_ru="Баскетбол",
        )
        self.tournament.allowed_sports.add(basketball)

        response = self.client.get(reverse("tournaments:index"))

        self.assertContains(response, "<small>Баскетбол</small>")

    def test_detail_icon_uses_admin_background_color(self):
        response = self.client.get(
            reverse("tournaments:detail", kwargs={"slug": self.tournament.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'class="tournament-detail-hero-icon" data-tournament-icon-color="#0F7A43"',
        )
