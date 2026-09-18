import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import (
    AnalystPaidPlan,
    AnalystProfile,
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
from cabinet.paid_predictions import subscribe_to_paid_predictions
from cabinet.roulette.models import RoulettePrize, RouletteSettings
from cabinet.roulette.spin_service import spin_roulette
from cabinet.roulette.state import UserRouletteState
from cabinet.services.bonus_rewards import grant_bonus_reward
from cabinet.services.daily_tasks import record_daily_task_action
from cabinet.services.referral_bonuses import (
    FIRST_SUBSCRIPTION_BONUS_TITLE,
    FIRST_TOPUP_BONUS_TITLE,
    REGISTRATION_BONUS_TITLE,
    grant_referral_registration_bonus,
)
from cabinet.services.streaks import touch_daily_streak
from cabinet.services.xp import build_level_progress, grant_xp, sync_user_level
from game.models import PredictionCoupon
from notifications.models import Notification, NotificationPreference
from wallets.models import CoinPackage, CoinSettings, CoinWallet
from wallets.services import purchase_coin_package


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
        notification = Notification.objects.get(
            event_key=f"bonus:{first_event.pk}",
        )
        self.assertEqual(notification.recipient, referrer)
        self.assertEqual(notification.kind, Notification.Kind.BONUS_REFERRAL)
        self.assertEqual(notification.url, reverse("cabinet:referrals"))


    def test_referral_link_registration_creates_bonus_event_and_notification(self):
        referrer = User.objects.create_user(
            username="link-referrer",
            password="test-password",
        )
        ReferralBonusSettings.objects.update_or_create(
            pk=1,
            defaults={
                "registration_reward_coins": 30,
                "registration_reward_xp": 0,
                "first_topup_reward_coins": 0,
                "first_subscription_reward_coins": 0,
                "is_enabled": True,
            },
        )

        referral_response = self.client.get(
            reverse(
                "front:capper_referral_code",
                kwargs={
                    "username": referrer.username,
                    "code": referrer.referral_code,
                },
            )
        )
        self.assertEqual(referral_response.status_code, 302)

        register_response = self.client.post(
            reverse("cabinet:register"),
            {
                "account_type": "user",
                "role": User.Role.READER,
                "username": "referred-by-link",
                "email": "referred-by-link@example.com",
                "first_name": "Referral",
                "last_name": "Reader",
                "password1": "ReferralPass123!",
                "password2": "ReferralPass123!",
                "accept_terms": "on",
            },
        )

        self.assertEqual(register_response.status_code, 302)
        referred_user = User.objects.get(username="referred-by-link")
        visit = ReferralVisit.objects.get(
            referrer=referrer,
            visitor=referred_user,
        )
        self.assertIsNotNone(visit.registered_at)

        event = BonusEvent.objects.get(
            user=referrer,
            event_type=BonusEvent.EventType.REFERRAL,
            title=REGISTRATION_BONUS_TITLE,
            related_model=visit._meta.label_lower,
            related_id=visit.pk,
        )
        notification = Notification.objects.get(
            event_key=f"bonus:{event.pk}",
        )
        self.assertEqual(notification.recipient, referrer)
        self.assertEqual(notification.kind, Notification.Kind.BONUS_REFERRAL)
        self.assertEqual(notification.url, reverse("cabinet:referrals"))

    def test_first_referral_topup_creates_bonus_event_and_notification(self):
        referrer = User.objects.create_user(
            username="topup-referrer",
            password="test-password",
        )
        ReferralBonusSettings.objects.update_or_create(
            pk=1,
            defaults={
                "registration_reward_coins": 0,
                "registration_reward_xp": 0,
                "first_topup_reward_coins": 40,
                "first_subscription_reward_coins": 0,
                "is_enabled": True,
            },
        )
        ReferralVisit.objects.create(
            referrer=referrer,
            visitor=self.user,
            session_key="topup-referral-session",
            registered_at=timezone.now(),
        )
        package = CoinPackage.objects.create(
            title="Referral topup",
            coins=100,
            price_rub=Decimal("500.00"),
        )

        purchase_coin_package(self.user, package)

        event = BonusEvent.objects.get(
            user=referrer,
            event_type=BonusEvent.EventType.REFERRAL,
            title=FIRST_TOPUP_BONUS_TITLE,
        )
        notification = Notification.objects.get(
            event_key=f"bonus:{event.pk}",
        )
        self.assertEqual(notification.recipient, referrer)
        self.assertEqual(notification.kind, Notification.Kind.BONUS_REFERRAL)
        self.assertEqual(notification.url, reverse("cabinet:referrals"))

    def test_first_referral_subscription_creates_bonus_event_and_notification(self):
        referrer = User.objects.create_user(
            username="subscription-referrer",
            password="test-password",
        )
        ReferralBonusSettings.objects.update_or_create(
            pk=1,
            defaults={
                "registration_reward_coins": 0,
                "registration_reward_xp": 0,
                "first_topup_reward_coins": 0,
                "first_subscription_reward_coins": 60,
                "is_enabled": True,
            },
        )
        ReferralVisit.objects.create(
            referrer=referrer,
            visitor=self.user,
            session_key="subscription-referral-session",
            registered_at=timezone.now(),
        )
        analyst = User.objects.create_user(
            username="paid-analyst",
            password="test-password",
            role=User.Role.ANALYST,
        )
        analyst_profile = AnalystProfile.objects.get(user=analyst)
        analyst_profile.display_name = "Paid analyst"
        analyst_profile.paid_predictions_enabled = True
        analyst_profile.is_public = True
        analyst_profile.save(
            update_fields=[
                "display_name",
                "paid_predictions_enabled",
                "is_public",
            ]
        )
        plan = AnalystPaidPlan.objects.create(
            analyst=analyst,
            title="30 дней",
            duration_days=30,
            price=Decimal("300.00"),
        )

        subscription = subscribe_to_paid_predictions(
            self.user,
            analyst,
            plan,
        )

        event = BonusEvent.objects.get(
            user=referrer,
            event_type=BonusEvent.EventType.REFERRAL,
            title=FIRST_SUBSCRIPTION_BONUS_TITLE,
            related_model=subscription._meta.label_lower,
            related_id=subscription.pk,
        )
        notification = Notification.objects.get(
            event_key=f"bonus:{event.pk}",
        )
        self.assertEqual(notification.recipient, referrer)
        self.assertEqual(notification.kind, Notification.Kind.BONUS_REFERRAL)
        self.assertEqual(notification.url, reverse("cabinet:referrals"))

        subscribe_to_paid_predictions(self.user, analyst, plan)
        self.assertEqual(
            BonusEvent.objects.filter(
                user=referrer,
                event_type=BonusEvent.EventType.REFERRAL,
                title=FIRST_SUBSCRIPTION_BONUS_TITLE,
            ).count(),
            1,
        )
        self.assertEqual(
            Notification.objects.filter(
                event_key=f"bonus:{event.pk}",
            ).count(),
            1,
        )

    def test_disabled_referral_notification_keeps_bonus_event(self):
        referrer = User.objects.create_user(
            username="silent-referrer",
            password="test-password",
        )
        NotificationPreference.objects.create(
            user=referrer,
            bonus_referral=False,
        )
        ReferralBonusSettings.objects.update_or_create(
            pk=1,
            defaults={
                "registration_reward_coins": 20,
                "registration_reward_xp": 0,
                "first_topup_reward_coins": 0,
                "first_subscription_reward_coins": 0,
                "is_enabled": True,
            },
        )
        visit = ReferralVisit.objects.create(
            referrer=referrer,
            visitor=self.user,
            session_key="silent-referral-session",
            registered_at=timezone.now(),
        )

        event = grant_referral_registration_bonus(visit)

        self.assertIsNotNone(event)
        self.assertTrue(BonusEvent.objects.filter(pk=event.pk).exists())
        self.assertFalse(
            Notification.objects.filter(
                event_key=f"bonus:{event.pk}",
            ).exists()
        )


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
        reward_event = BonusEvent.objects.get(
            user=self.user,
            event_type=BonusEvent.EventType.DAILY_TASK,
            related_model=progress._meta.label_lower,
            related_id=progress.pk,
        )
        reward_notification = Notification.objects.get(
            event_key=f"bonus:{reward_event.pk}",
        )
        self.assertEqual(reward_notification.title, "Награда получена")
        self.assertEqual(
            Notification.objects.filter(
                event_key=f"bonus:{reward_event.pk}",
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

    def test_daily_task_completion_creates_notification_once(self):
        task = DailyTask.objects.create(
            title="Открыть ленту дважды",
            audience=DailyTask.Audience.ALL,
            task_type=DailyTask.TaskType.OPEN_FEED,
            target_value=2,
        )
        progress_date = timezone.localdate()
        event_key = (
            f"daily-task-completed:{self.user.pk}:{task.pk}:{progress_date}"
        )

        record_daily_task_action(
            self.user,
            DailyTask.TaskType.OPEN_FEED,
        )
        self.assertFalse(
            Notification.objects.filter(event_key=event_key).exists()
        )

        record_daily_task_action(
            self.user,
            DailyTask.TaskType.OPEN_FEED,
        )
        notification = Notification.objects.get(event_key=event_key)

        self.assertEqual(
            notification.kind,
            Notification.Kind.BONUS_DAILY_TASK,
        )
        self.assertEqual(notification.title, "Задание выполнено")
        self.assertEqual(notification.message, task.title)
        self.assertEqual(
            notification.url,
            reverse("cabinet:bonus_tasks"),
        )
        self.assertEqual(notification.meta["daily_task_id"], task.pk)
        self.assertEqual(
            notification.meta["progress_date"],
            str(progress_date),
        )

        record_daily_task_action(
            self.user,
            DailyTask.TaskType.OPEN_FEED,
        )
        self.assertEqual(
            Notification.objects.filter(event_key=event_key).count(),
            1,
        )

    def test_disabled_daily_task_notifications_skip_completion_notification(self):
        preferences, _ = NotificationPreference.objects.get_or_create(
            user=self.user,
        )
        preferences.bonus_daily_task = False
        preferences.save(
            update_fields=["bonus_daily_task", "updated_at"],
        )
        task = DailyTask.objects.create(
            title="Открыть ленту",
            audience=DailyTask.Audience.ALL,
            task_type=DailyTask.TaskType.OPEN_FEED,
            target_value=1,
        )

        record_daily_task_action(
            self.user,
            DailyTask.TaskType.OPEN_FEED,
        )

        event_key = (
            f"daily-task-completed:{self.user.pk}:{task.pk}:"
            f"{timezone.localdate()}"
        )
        self.assertFalse(
            Notification.objects.filter(event_key=event_key).exists()
        )

    def test_bonus_reward_creates_notification_after_event(self):
        preferences = NotificationPreference.objects.create(
            user=self.user,
            bonus_roulette=True,
        )
        cases = (
            (
                BonusEvent.EventType.DAILY_TASK,
                Notification.Kind.BONUS_DAILY_TASK,
                reverse("cabinet:bonus_tasks"),
            ),
            (
                BonusEvent.EventType.STREAK,
                Notification.Kind.BONUS_STREAK,
                reverse("cabinet:bonuses"),
            ),
            (
                BonusEvent.EventType.ROULETTE,
                Notification.Kind.BONUS_ROULETTE,
                reverse("cabinet:bonuses"),
            ),
            (
                BonusEvent.EventType.REFERRAL,
                Notification.Kind.BONUS_REFERRAL,
                reverse("cabinet:referrals"),
            ),
        )

        for index, (event_type, notification_kind, expected_url) in enumerate(cases, start=1):
            event = grant_bonus_reward(
                self.user,
                coins=index,
                event_type=event_type,
                title=f"Бонус {index}",
                description=f"Описание {index}",
            )
            notification = Notification.objects.get(event_key=f"bonus:{event.pk}")

            self.assertEqual(notification.kind, notification_kind)
            expected_title = (
                "Награда получена"
                if event_type == BonusEvent.EventType.DAILY_TASK
                else event.title
            )
            self.assertEqual(notification.title, expected_title)
            expected_message = f"+{index} монет · {event.description}"
            if event_type == BonusEvent.EventType.DAILY_TASK:
                expected_message = f"{event.title} · {expected_message}"
            self.assertEqual(notification.message, expected_message)
            self.assertEqual(notification.url, expected_url)
            self.assertEqual(notification.meta["bonus_event_id"], event.pk)

        preferences.refresh_from_db()
        self.assertTrue(preferences.bonus_roulette)

    def test_level_notification_created_only_when_level_increases(self):
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
        state = UserXpState.objects.create(
            user=self.user,
            level=1,
            xp=90,
        )

        sync_user_level(state)
        self.assertFalse(
            Notification.objects.filter(kind=Notification.Kind.BONUS_LEVEL).exists()
        )

        grant_xp(self.user, 10)

        state.refresh_from_db()
        self.assertEqual(state.level, 2)
        notification = Notification.objects.get(kind=Notification.Kind.BONUS_LEVEL)
        self.assertEqual(notification.url, reverse("cabinet:bonus_levels"))
        self.assertEqual(
            notification.event_key,
            f"bonus-level:{self.user.pk}:2:{state.xp}",
        )

        sync_user_level(state)
        self.assertEqual(
            Notification.objects.filter(kind=Notification.Kind.BONUS_LEVEL).count(),
            1,
        )

    def test_bonus_page_uses_prepared_navigation_links(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("cabinet:bonuses"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["daily_tasks_card"]["url"],
            reverse("cabinet:bonus_tasks"),
        )
        self.assertEqual(
            response.context["bonus_page"]["levels"]["url"],
            reverse("cabinet:bonus_levels"),
        )
        self.assertEqual(
            response.context["referral_card"]["url"],
            reverse("cabinet:referrals"),
        )
        self.assertEqual(
            response.context["bonus_page"]["notification_settings"]["url"],
            reverse("notifications:center"),
        )
        self.assertContains(response, reverse("cabinet:bonus_tasks"))
        self.assertContains(response, reverse("cabinet:bonus_levels"))
        self.assertContains(response, reverse("cabinet:referrals"))
        self.assertContains(response, reverse("notifications:center"))

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

    def test_daily_tasks_page_requires_login(self):
        response = self.client.get(reverse("cabinet:bonus_tasks"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_daily_tasks_page_filters_tasks_by_user_role(self):
        reader_task = DailyTask.objects.create(
            title="Задание читателя",
            audience=DailyTask.Audience.READER,
            task_type=DailyTask.TaskType.OPEN_FEED,
            target_value=1,
        )
        capper_task = DailyTask.objects.create(
            title="Задание каппера",
            audience=DailyTask.Audience.CAPPER,
            task_type=DailyTask.TaskType.CREATE_PREDICTION,
            target_value=1,
        )
        common_task = DailyTask.objects.create(
            title="Общее задание",
            audience=DailyTask.Audience.ALL,
            task_type=DailyTask.TaskType.VIEW_PREDICTION,
            target_value=1,
        )
        capper = User.objects.create_user(
            username="bonus-page-capper",
            password="test-password",
            role=User.Role.ANALYST,
        )

        self.client.force_login(self.user)
        reader_response = self.client.get(reverse("cabinet:bonus_tasks"))
        reader_task_ids = {
            task["id"]
            for task in reader_response.context["tasks"]
        }

        self.client.force_login(capper)
        capper_response = self.client.get(reverse("cabinet:bonus_tasks"))
        capper_task_ids = {
            task["id"]
            for task in capper_response.context["tasks"]
        }

        self.assertEqual(reader_response.status_code, 200)
        self.assertEqual(capper_response.status_code, 200)
        self.assertIn(reader_task.pk, reader_task_ids)
        self.assertIn(common_task.pk, reader_task_ids)
        self.assertNotIn(capper_task.pk, reader_task_ids)
        self.assertIn(capper_task.pk, capper_task_ids)
        self.assertIn(common_task.pk, capper_task_ids)
        self.assertNotIn(reader_task.pk, capper_task_ids)
        self.assertEqual(
            reader_response.context["daily_tasks_card"]["summary_label"],
            "Сегодня выполнено 0 из 2",
        )
        reader_common_task = next(
            task
            for task in reader_response.context["tasks"]
            if task["id"] == common_task.pk
        )
        self.assertEqual(reader_common_task["progress_label"], "0 / 1")
        self.assertEqual(reader_common_task["row_class"], "is-in-progress")
        self.assertEqual(reader_common_task["display_status_label"], "В процессе")
        self.assertNotContains(reader_response, "bonus-center-aside")

    def test_bonus_tasks_page_only_renders_claim_button_when_claimable(self):
        task = DailyTask.objects.create(
            title="Задание с наградой",
            audience=DailyTask.Audience.ALL,
            task_type=DailyTask.TaskType.OPEN_FEED,
            target_value=1,
            reward_coins=10,
        )
        self.client.force_login(self.user)

        initial_response = self.client.get(reverse("cabinet:bonus_tasks"))
        self.assertNotContains(initial_response, "data-bonus-task-claim")

        record_daily_task_action(
            self.user,
            DailyTask.TaskType.OPEN_FEED,
        )
        claimable_response = self.client.get(reverse("cabinet:bonus_tasks"))

        claimable_task = next(
            item
            for item in claimable_response.context["tasks"]
            if item["id"] == task.pk
        )
        self.assertTrue(claimable_task["can_claim"])
        self.assertEqual(claimable_task["row_class"], "is-completed")
        self.assertEqual(claimable_task["display_status_label"], "Выполнено")
        self.assertContains(claimable_response, "data-bonus-task-claim")
        self.assertContains(claimable_response, "bonus-task-check")

    def test_bonus_levels_page_shows_current_level(self):
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
        XpLevel.objects.create(
            level=3,
            title="Опытный",
            required_xp=200,
            order=3,
        )
        UserXpState.objects.create(
            user=self.user,
            level=2,
            xp=120,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("cabinet:bonus_levels"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["level_progress"]["level"], 2)
        self.assertEqual(response.context["level_progress"]["level_title"], "Участник")

        levels = {
            level["level"]: level
            for level in response.context["levels"]
        }
        self.assertEqual(levels[1]["progress_percent"], 100)
        self.assertEqual(levels[1]["progress_class"], "is-progress-100")
        self.assertEqual(levels[1]["status_label"], "Открыт")
        self.assertTrue(levels[1]["is_unlocked"])
        self.assertFalse(levels[1]["is_current"])
        self.assertFalse(levels[1]["is_locked"])

        self.assertEqual(levels[2]["progress_percent"], 20)
        self.assertEqual(levels[2]["progress_class"], "is-progress-20")
        self.assertEqual(levels[2]["status_label"], "Текущий")
        self.assertFalse(levels[2]["is_unlocked"])
        self.assertTrue(levels[2]["is_current"])
        self.assertFalse(levels[2]["is_locked"])

        self.assertEqual(levels[3]["progress_percent"], 0)
        self.assertEqual(levels[3]["progress_class"], "is-progress-0")
        self.assertEqual(levels[3]["status_label"], "Впереди")
        self.assertFalse(levels[3]["is_unlocked"])
        self.assertFalse(levels[3]["is_current"])
        self.assertTrue(levels[3]["is_locked"])
        self.assertContains(response, "Участник")

    def test_referrals_page_returns_url_and_stats(self):
        visitor = User.objects.create_user(
            username="referral-page-visitor",
            password="test-password",
        )
        now = timezone.now()
        ReferralVisit.objects.create(
            referrer=self.user,
            visitor=visitor,
            session_key="registered-visitor",
            visits_count=3,
            registered_at=now,
            subscribed_at=now,
        )
        ReferralVisit.objects.create(
            referrer=self.user,
            session_key="anonymous-visitor",
            visits_count=2,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("cabinet:referrals"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.user.referral_code, response.context["referral_url"])
        self.assertEqual(response.context["visitors_count"], 2)
        self.assertEqual(response.context["clicks_count"], 5)
        self.assertEqual(response.context["registrations_count"], 1)
        self.assertEqual(response.context["subscriptions_count"], 1)
        self.assertEqual(response.context["conversion"], 50.0)
        self.assertEqual(response.context["bonus_events_count"], 0)
        self.assertEqual(
            [metric["key"] for metric in response.context["metrics"]],
            ["clicks", "registrations", "subscriptions", "bonuses"],
        )
        self.assertEqual(len(response.context["bonus_steps"]), 3)
        self.assertContains(response, "Как начисляются бонусы")
        self.assertContains(response, "Последние рефералы")
        self.assertContains(response, "Последние бонусы")
        self.assertNotContains(response, "Уникальные посетители")
        self.assertNotContains(response, "Конверсия")

    def test_referrals_page_shows_income_metric_for_capper(self):
        capper = User.objects.create_user(
            username="referral-page-capper",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(capper)

        response = self.client.get(reverse("cabinet:referrals"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [metric["key"] for metric in response.context["metrics"]],
            ["clicks", "registrations", "subscriptions", "bonuses", "income"],
        )
        self.assertContains(response, "Заработано")

    def test_referral_stats_matches_ssr_context_metrics(self):
        visitor = User.objects.create_user(
            username="referral-stats-visitor",
            password="test-password",
        )
        now = timezone.now()
        ReferralVisit.objects.create(
            referrer=self.user,
            visitor=visitor,
            session_key="stats-registered",
            visits_count=4,
            registered_at=now,
        )
        ReferralVisit.objects.create(
            referrer=self.user,
            session_key="stats-anonymous",
            visits_count=1,
        )
        self.client.force_login(self.user)

        page_response = self.client.get(reverse("cabinet:referrals"))
        stats_response = self.client.get(reverse("cabinet:referral_stats"))
        payload = stats_response.json()

        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(stats_response.status_code, 200)
        for key in (
            "referral_url",
            "referral_code",
            "visitors_count",
            "clicks_count",
            "registrations_count",
            "subscriptions_count",
            "conversion",
        ):
            self.assertEqual(payload[key], page_response.context[key])

    def test_disabled_bonus_notification_preference_skips_notification(self):
        NotificationPreference.objects.create(
            user=self.user,
            bonus_daily_task=False,
        )

        event = grant_bonus_reward(
            self.user,
            coins=10,
            event_type=BonusEvent.EventType.DAILY_TASK,
            title="Отключённое уведомление",
            description="Награда начислена",
        )

        self.assertFalse(
            Notification.objects.filter(event_key=f"bonus:{event.pk}").exists()
        )
        self.assertTrue(
            BonusEvent.objects.filter(pk=event.pk, user=self.user).exists()
        )

    def test_profile_tab_receives_bonus_summary(self):
        DailyTask.objects.create(
            title="Задание профиля",
            audience=DailyTask.Audience.ALL,
            task_type=DailyTask.TaskType.OPEN_FEED,
            target_value=1,
        )
        XpLevel.objects.create(
            level=1,
            title="Новичок",
            icon="xp_levels/icons/test-icon.png",
            image="xp_levels/images/test-image.png",
            required_xp=0,
            order=1,
        )
        XpLevel.objects.create(
            level=2,
            title="Участник",
            required_xp=100,
            order=2,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("cabinet:profile"),
            {"tab": "profile"},
        )

        self.assertEqual(response.status_code, 200)
        summary = response.context["profile_bonus_summary"]
        self.assertIsNotNone(summary)
        self.assertIn("daily_tasks", summary)
        self.assertEqual(summary["daily_tasks_title"], "Ежедневные задания")
        self.assertEqual(len(summary["daily_tasks"]), 1)
        self.assertEqual(summary["daily_tasks"][0]["progress_label"], "0 / 1")
        hero = summary["hero"]
        self.assertEqual(hero["current_level_title"], "Новичок")
        self.assertEqual(hero["current_level_number"], 1)
        self.assertEqual(hero["xp"], 0)
        self.assertEqual(hero["target_label"], "из 100")
        self.assertEqual(hero["status_label"], "100 XP до следующего уровня")
        self.assertEqual(hero["progress_class"], "is-progress-0")
        self.assertTrue(hero["icon_url"].endswith("xp_levels/icons/test-icon.png"))
        self.assertTrue(hero["image_url"].endswith("xp_levels/images/test-image.png"))
        self.assertContains(response, "profile-xp-card")
        self.assertEqual(summary["tasks_url"], reverse("cabinet:bonus_tasks"))
        self.assertEqual(summary["tasks_link_label"], "Все задания")
        self.assertContains(response, "Ежедневные задания")
        self.assertContains(response, "Все задания")
        self.assertEqual(summary["levels_url"], reverse("cabinet:bonus_levels"))
        self.assertEqual(summary["bonuses_url"], reverse("cabinet:bonuses"))
        self.assertEqual(
            summary["notifications_url"],
            reverse("notifications:center"),
        )



    def test_profile_daily_tasks_show_all_today_tasks_and_claim_button(self):
        tasks = [
            DailyTask.objects.create(
                title=f"Задание профиля {index}",
                audience=DailyTask.Audience.ALL,
                task_type=DailyTask.TaskType.OPEN_FEED,
                target_value=1,
                order=index,
            )
            for index in range(1, 5)
        ]
        UserDailyTaskProgress.objects.create(
            user=self.user,
            task=tasks[0],
            progress_date=timezone.localdate(),
            current_value=1,
            is_completed=True,
            completed_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("cabinet:profile"),
            {"tab": "profile"},
        )

        summary = response.context["profile_bonus_summary"]
        self.assertEqual(len(summary["daily_tasks"]), 4)
        self.assertTrue(summary["daily_tasks"][0]["can_claim"])
        self.assertEqual(
            summary["daily_tasks"][0]["row_class"],
            "is-completed",
        )
        self.assertEqual(
            summary["daily_tasks"][1]["progress_label"],
            "0 / 1",
        )
        self.assertContains(response, "data-profile-daily-task-claim")
        self.assertContains(response, "profile-daily-task-check")
        for task in tasks:
            self.assertContains(response, task.title)
