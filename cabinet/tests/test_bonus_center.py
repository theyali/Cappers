import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import (
    BonusEvent,
    DailyTask,
    ReferralBonusSettings,
    ReferralVisit,
    User,
    UserDailyStreak,
    UserDailyTaskProgress,
    UserXpState,
    XpLevel,
)
from cabinet.roulette.models import RoulettePrize, RouletteSettings
from cabinet.roulette.spin_service import spin_roulette
from cabinet.roulette.state import UserRouletteState
from cabinet.services.bonus_rewards import grant_bonus_reward
from cabinet.services.referral_bonuses import grant_referral_registration_bonus
from cabinet.services.streaks import touch_daily_streak
from cabinet.services.xp import build_level_progress
from game.models import PredictionCoupon
from wallets.models import CoinSettings, CoinWallet


class BonusCenterServiceTests(TestCase):
    def setUp(self):
        CoinSettings.objects.update_or_create(
            pk=1,
            defaults={
                "initial_grant": 0,
                "is_enabled": True,
            },
        )
        RouletteSettings.objects.update_or_create(
            pk=1,
            defaults={
                "is_enabled": True,
                "daily_free_spins": 0,
                "reset_hour": 0,
            },
        )
        self.user = User.objects.create_user(
            username="bonus-center-user",
            password="test-password",
        )

    def test_daily_task_progress_cannot_duplicate_same_day(self):
        task = DailyTask.objects.create(
            title="Открыть бонусы",
            task_type=DailyTask.TaskType.DAILY_LOGIN,
            target_value=1,
        )
        progress_date = timezone.localdate()

        UserDailyTaskProgress.objects.create(
            user=self.user,
            task=task,
            progress_date=progress_date,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserDailyTaskProgress.objects.create(
                    user=self.user,
                    task=task,
                    progress_date=progress_date,
                )

        self.assertEqual(
            UserDailyTaskProgress.objects.filter(
                user=self.user,
                task=task,
                progress_date=progress_date,
            ).count(),
            1,
        )

    def test_grant_bonus_reward_updates_all_balances_and_creates_event(self):
        XpLevel.objects.create(
            level=1,
            title="Новичок",
            required_xp=0,
            order=1,
        )
        XpLevel.objects.create(
            level=2,
            title="Участник",
            required_xp=100,
            order=2,
        )

        event = grant_bonus_reward(
            self.user,
            xp=120,
            coins=30,
            spins=2,
            event_type=BonusEvent.EventType.DAILY_TASK,
            title="Тестовая награда",
        )

        xp_state = UserXpState.objects.get(user=self.user)
        coin_wallet = CoinWallet.objects.get(user=self.user)
        roulette_state = UserRouletteState.objects.get(user=self.user)

        self.assertEqual(xp_state.xp, 120)
        self.assertEqual(xp_state.level, 2)
        self.assertEqual(coin_wallet.balance, 30)
        self.assertEqual(roulette_state.available_spins, 2)
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.event_type, BonusEvent.EventType.DAILY_TASK)
        self.assertEqual(event.xp_delta, 120)
        self.assertEqual(event.coin_delta, 30)
        self.assertEqual(event.spin_delta, 2)

    def test_touch_daily_streak_handles_today_yesterday_and_gap(self):
        now = timezone.now()
        today = timezone.localdate(now)
        state = UserDailyStreak.objects.create(
            user=self.user,
            current_days=2,
            best_days=2,
            last_seen_date=today,
        )

        same_day = touch_daily_streak(self.user, now=now)
        self.assertEqual(same_day.current_days, 2)
        self.assertEqual(same_day.best_days, 2)

        state.current_days = 2
        state.best_days = 2
        state.last_seen_date = today - timedelta(days=1)
        state.save(
            update_fields=("current_days", "best_days", "last_seen_date", "updated_at")
        )

        consecutive_day = touch_daily_streak(self.user, now=now)
        self.assertEqual(consecutive_day.current_days, 3)
        self.assertEqual(consecutive_day.best_days, 3)

        state.refresh_from_db()
        state.current_days = 7
        state.best_days = 7
        state.last_seen_date = today - timedelta(days=3)
        state.save(
            update_fields=("current_days", "best_days", "last_seen_date", "updated_at")
        )

        after_gap = touch_daily_streak(self.user, now=now)
        self.assertEqual(after_gap.current_days, 1)
        self.assertEqual(after_gap.best_days, 7)

    def test_spin_roulette_creates_one_bonus_event(self):
        RoulettePrize.objects.create(
            title="VIP на день",
            short_text="VIP на 1 день",
            reward_type=RoulettePrize.RewardType.VIP_DAYS,
            reward_value=1,
            weight=1,
            is_active=True,
            sector_order=0,
        )
        UserRouletteState.objects.create(
            user=self.user,
            available_spins=1,
        )
        operation_id = uuid.uuid4()

        first_spin = spin_roulette(self.user, operation_id)
        repeated_spin = spin_roulette(self.user, operation_id)

        self.assertEqual(repeated_spin.pk, first_spin.pk)
        self.assertEqual(
            BonusEvent.objects.filter(
                user=self.user,
                event_type=BonusEvent.EventType.ROULETTE,
                related_model=first_spin._meta.label_lower,
                related_id=first_spin.pk,
            ).count(),
            1,
        )

    def test_referral_registration_bonus_is_granted_once(self):
        referrer = User.objects.create_user(
            username="bonus-referrer",
            password="test-password",
        )
        ReferralBonusSettings.objects.update_or_create(
            pk=1,
            defaults={
                "registration_reward_coins": 25,
                "registration_reward_xp": 10,
                "first_topup_reward_coins": 0,
                "first_subscription_reward_coins": 0,
                "max_visible_reward_text": "До 25 монет",
                "is_enabled": True,
            },
        )
        visit = ReferralVisit.objects.create(
            referrer=referrer,
            visitor=self.user,
            session_key="bonus-registration-session",
            registered_at=timezone.now(),
        )

        first_event = grant_referral_registration_bonus(visit)
        repeated_event = grant_referral_registration_bonus(visit)

        self.assertIsNotNone(first_event)
        self.assertIsNone(repeated_event)
        self.assertEqual(
            BonusEvent.objects.filter(
                user=referrer,
                event_type=BonusEvent.EventType.REFERRAL,
                related_model=visit._meta.label_lower,
                related_id=visit.pk,
            ).count(),
            1,
        )

        xp_state = UserXpState.objects.get(user=referrer)
        coin_wallet = CoinWallet.objects.get(user=referrer)
        self.assertEqual(xp_state.xp, 10)
        self.assertEqual(coin_wallet.balance, 25)


    def test_level_progress_uses_ten_percent_bucket_class(self):
        XpLevel.objects.create(
            level=1,
            title="Новичок",
            required_xp=0,
            order=1,
        )
        XpLevel.objects.create(
            level=2,
            title="Участник",
            required_xp=100,
            order=2,
        )
        UserXpState.objects.create(
            user=self.user,
            level=1,
            xp=54,
        )

        progress = build_level_progress(self.user)

        self.assertEqual(progress["progress_percent"], 54)
        self.assertEqual(progress["progress_class"], "is-progress-50")

    def test_daily_task_claim_rejects_incomplete_task(self):
        task = DailyTask.objects.create(
            title="Невыполненное задание",
            task_type=DailyTask.TaskType.OPEN_FEED,
            target_value=2,
            reward_xp=15,
            reward_coins=20,
            reward_spins=1,
        )
        UserDailyTaskProgress.objects.create(
            user=self.user,
            task=task,
            progress_date=timezone.localdate(),
            current_value=1,
            is_completed=False,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("cabinet:daily_task_claim", args=(task.pk,))
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(
            BonusEvent.objects.filter(
                user=self.user,
                event_type=BonusEvent.EventType.DAILY_TASK,
            ).count(),
            0,
        )
        self.assertFalse(UserXpState.objects.filter(user=self.user).exists())
        self.assertFalse(CoinWallet.objects.filter(user=self.user).exists())
        self.assertFalse(UserRouletteState.objects.filter(user=self.user).exists())

    def test_daily_task_claim_endpoint_returns_updated_bonus_state_once(self):
        task = DailyTask.objects.create(
            title="Забрать награду",
            task_type=DailyTask.TaskType.DAILY_LOGIN,
            target_value=1,
            reward_xp=15,
            reward_coins=20,
            reward_spins=1,
        )
        UserDailyTaskProgress.objects.create(
            user=self.user,
            task=task,
            progress_date=timezone.localdate(),
            current_value=1,
            is_completed=True,
            completed_at=timezone.now(),
        )
        self.client.force_login(self.user)
        url = reverse("cabinet:daily_task_claim", args=(task.pk,))

        first_response = self.client.post(url)
        second_response = self.client.post(url)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(second_response.json()["ok"])
        payload = first_response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("daily_tasks_card", payload)
        self.assertIn("level_progress", payload)
        self.assertIn("recent_gifts", payload)
        self.assertEqual(payload["available_spins"], 1)

        progress = UserDailyTaskProgress.objects.get(
            user=self.user,
            task=task,
            progress_date=timezone.localdate(),
        )
        self.assertIsNotNone(progress.reward_claimed_at)
        self.assertEqual(
            BonusEvent.objects.filter(
                user=self.user,
                event_type=BonusEvent.EventType.DAILY_TASK,
                related_model=progress._meta.label_lower,
                related_id=progress.pk,
            ).count(),
            1,
        )
        self.assertEqual(UserXpState.objects.get(user=self.user).xp, 15)
        self.assertEqual(CoinWallet.objects.get(user=self.user).balance, 20)
        self.assertEqual(
            UserRouletteState.objects.get(user=self.user).available_spins,
            1,
        )

    def test_daily_task_claim_endpoint_requires_post(self):
        task = DailyTask.objects.create(
            title="Награда только POST",
            task_type=DailyTask.TaskType.DAILY_LOGIN,
            target_value=1,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("cabinet:daily_task_claim", args=(task.pk,))
        )

        self.assertEqual(response.status_code, 405)


    def test_daily_task_claim_endpoint_requires_login(self):
        task = DailyTask.objects.create(
            title="Награда после входа",
            task_type=DailyTask.TaskType.DAILY_LOGIN,
            target_value=1,
        )

        response = self.client.post(
            reverse("cabinet:daily_task_claim", args=(task.pk,))
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)


    def test_prediction_favorite_route_records_daily_task_only_on_add(self):
        analyst = User.objects.create_user(
            username="bonus-favorite-analyst",
            password="test-password",
            role=User.Role.ANALYST,
        )
        prediction = PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.FREE,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("180.00"),
            confidence=70,
        )
        task = DailyTask.objects.create(
            title="Добавить в избранное",
            task_type=DailyTask.TaskType.ADD_FAVORITE,
            target_value=2,
        )
        self.client.force_login(self.user)
        url = reverse("front:prediction_favorite", args=(prediction.pk,))

        add_response = self.client.post(url)

        self.assertEqual(add_response.status_code, 200)
        self.assertTrue(add_response.json()["active"])
        progress = UserDailyTaskProgress.objects.get(
            user=self.user,
            task=task,
            progress_date=timezone.localdate(),
        )
        self.assertEqual(progress.current_value, 1)

        remove_response = self.client.post(url)

        self.assertEqual(remove_response.status_code, 200)
        self.assertFalse(remove_response.json()["active"])
        progress.refresh_from_db()
        self.assertEqual(progress.current_value, 1)

    def test_bonus_page_shows_claim_button_for_completed_task(self):
        task = DailyTask.objects.create(
            title="Получить бонус",
            task_type=DailyTask.TaskType.ADD_FAVORITE,
            target_value=1,
            reward_xp=5,
        )
        UserDailyTaskProgress.objects.create(
            user=self.user,
            task=task,
            progress_date=timezone.localdate(),
            current_value=1,
            is_completed=True,
            completed_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("cabinet:bonuses"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-daily-task-claim")
        self.assertContains(
            response,
            reverse("cabinet:daily_task_claim", args=(task.pk,)),
        )
        self.assertContains(response, ">Получить</span>")
