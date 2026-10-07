from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from cabinet.models import User, UserDailyStreak
from game.services.providers.neurokeff import NeurokeffSportsProvider
from notifications import tasks as notification_tasks


class UserTimezoneDayTests(TestCase):
    def _visit(self, username, timezone_name):
        user = User.objects.create_user(username=username, password="safe-test-password")
        self.client.force_login(user)
        self.client.cookies["cappers_tz"] = timezone_name
        self.client.get("/health/")
        return UserDailyStreak.objects.get(user=user).last_seen_date

    def test_daily_streak_counts_the_day_in_the_users_timezone(self):
        # UTC+14 and UTC-11 are always on different calendar days, so a single
        # server timezone could never produce both dates.
        now = timezone.now()
        for username, timezone_name in (("tz-east", "Pacific/Kiritimati"), ("tz-west", "Pacific/Pago_Pago")):
            with self.subTest(timezone_name=timezone_name):
                self.assertEqual(
                    self._visit(username, timezone_name),
                    timezone.localdate(now, ZoneInfo(timezone_name)),
                )


class FinishedMatchesWindowTests(TestCase):
    @override_settings(NEUROKEFF_FINISHED_DAYS_BACK=1)
    def test_yesterday_is_always_collected(self):
        provider = NeurokeffSportsProvider(sports=[{"code": "football", "id": 1}])

        with patch.object(provider, "_fetch_matches", return_value=[]) as fetch:
            provider.fetch_finished_matches("football")

        today = timezone.localdate()
        self.assertEqual(
            [call.kwargs["date_value"] for call in fetch.call_args_list],
            [today - timedelta(days=1), today],
        )


class AchievementSyncBatchTests(TestCase):
    def setUp(self):
        cache.delete(notification_tasks.ACHIEVEMENT_SYNC_CURSOR_KEY)
        self.users = [User.objects.create_user(username=f"ach-{index}", password="safe-test-password") for index in range(3)]

    def tearDown(self):
        cache.delete(notification_tasks.ACHIEVEMENT_SYNC_CURSOR_KEY)

    def test_users_are_checked_in_batches_and_the_cycle_restarts(self):
        checked = []

        def fake_sync(user, notify):
            checked.append(user.pk)
            return []

        first_id = User.objects.filter(is_active=True).order_by("id").values_list("id", flat=True).first()
        cache.set(notification_tasks.ACHIEVEMENT_SYNC_CURSOR_KEY, first_id - 1)
        with (
            patch.object(notification_tasks, "ACHIEVEMENT_SYNC_BATCH_SIZE", 2),
            patch("notifications.tasks.sync_user_achievements", side_effect=fake_sync),
        ):
            notification_tasks.sync_achievement_notifications()
            notification_tasks.sync_achievement_notifications()

        all_ids = list(User.objects.filter(is_active=True).order_by("id").values_list("id", flat=True))
        self.assertEqual(checked, all_ids)
        self.assertEqual(cache.get(notification_tasks.ACHIEVEMENT_SYNC_CURSOR_KEY), 0)
