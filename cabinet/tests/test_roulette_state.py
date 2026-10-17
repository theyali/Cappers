from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from cabinet.models import User
from cabinet.roulette.models import RouletteSettings
from cabinet.roulette.services import get_user_roulette_state, grant_user_roulette_spins
from cabinet.roulette.state import UserRouletteState


class RouletteCooldownTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cooldown-reader")
        self.settings, _ = RouletteSettings.objects.update_or_create(
            pk=1, defaults={"is_enabled": True, "daily_free_spins": 1, "reset_hour": 0},
        )
        self.now = datetime(2026, 10, 17, 20, tzinfo=ZoneInfo("Asia/Baku"))

    def state(self, now=None):
        return get_user_roulette_state(self.user, now=now or self.now)

    def consume(self, state, now=None):
        state.consume_spin(now=now or self.now, roulette_settings=self.settings)

    def test_first_free_attempt_is_immediate_and_visits_do_not_start_a_timer(self):
        state = self.state()
        self.assertEqual(state.available_spins, 1)
        self.assertEqual(state.last_daily_grant_at, self.now)
        self.assertIsNone(state.next_spin_at)
        for delay in (timedelta(hours=1), timedelta(days=1), timedelta(days=10)):
            state = self.state(self.now + delay)
            self.assertEqual(state.available_spins, 1)
            self.assertIsNone(state.next_spin_at)
        used_at = self.now + timedelta(days=10, hours=3)
        self.consume(state, used_at)
        self.assertEqual(state.next_spin_at, used_at + timedelta(hours=24))

    def test_midnight_and_one_second_before_24_hours_do_not_refill(self):
        state = self.state()
        self.consume(state)
        expected = self.now + timedelta(hours=24)
        for delay in (timedelta(hours=4), timedelta(hours=23, minutes=59, seconds=59)):
            state = self.state(self.now + delay)
            self.assertEqual(state.available_spins, 0)
            self.assertEqual(state.next_spin_at, expected)
            with self.assertRaisesMessage(ValidationError, "Нет доступных попыток"):
                self.consume(state, self.now + delay)

    def test_exactly_24_hours_grants_once_and_missed_periods_do_not_accumulate(self):
        state = self.state()
        self.consume(state)
        ready_at = self.now + timedelta(hours=24)
        state = self.state(ready_at)
        self.assertEqual(state.available_spins, 1)
        self.assertIsNone(state.next_spin_at)
        self.assertEqual(self.state(ready_at).available_spins, 1)
        self.assertEqual(self.state(ready_at + timedelta(days=10)).available_spins, 1)

    def test_old_calendar_timer_is_replaced_from_the_last_actual_spin(self):
        UserRouletteState.objects.create(
            user=self.user, available_spins=0, last_spin_at=self.now,
            last_daily_grant_at=self.now.replace(hour=0), next_spin_at=self.now + timedelta(hours=4),
        )
        state = self.state(self.now + timedelta(hours=4))
        self.assertEqual(state.available_spins, 0)
        self.assertEqual(state.next_spin_at, self.now + timedelta(hours=24))

    def test_clock_ignores_timezone_changes_and_daylight_saving_time(self):
        used_at = datetime(2026, 10, 25, 0, 30, tzinfo=ZoneInfo("Europe/Berlin"))
        state = self.state(used_at)
        self.consume(state, used_at)
        expected = used_at.astimezone(datetime_timezone.utc) + timedelta(hours=24)
        self.assertEqual(state.next_spin_at, expected)
        self.assertEqual(state.next_spin_at.astimezone(ZoneInfo("Europe/Berlin")).hour, 23)
        with timezone.override("Pacific/Auckland"):
            self.assertEqual(self.state(expected - timedelta(seconds=1)).available_spins, 0)
            self.assertEqual(self.state(expected).available_spins, 1)

    def test_extra_spins_are_spendable_during_cooldown_and_restart_it(self):
        state = self.state()
        self.consume(state)
        extra_at = self.now + timedelta(hours=2)
        state = grant_user_roulette_spins(self.user, 2, now=extra_at)
        self.assertEqual(state.available_spins, 2)
        self.assertEqual(state.next_spin_at, self.now + timedelta(hours=24))
        self.consume(state, extra_at)
        self.assertEqual(state.available_spins, 1)
        self.assertEqual(state.next_spin_at, extra_at + timedelta(hours=24))
        self.assertEqual(self.state(self.now + timedelta(hours=24)).available_spins, 1)
        self.assertEqual(self.state(extra_at + timedelta(hours=24)).available_spins, 2)

    def test_granting_extra_spins_persists_the_free_grant_marker(self):
        state = grant_user_roulette_spins(self.user, 2, now=self.now)
        state.refresh_from_db()
        self.assertEqual(state.available_spins, 3)
        self.assertEqual(state.last_daily_grant_at, self.now)
        self.assertEqual(self.state().available_spins, 3)

    def test_disabled_or_zero_allowance_preserves_existing_spins_without_timer(self):
        state = self.state()
        self.consume(state)
        grant_user_roulette_spins(self.user, 2, now=self.now)
        for is_enabled, allowance in ((False, 1), (True, 0)):
            with self.subTest(is_enabled=is_enabled, allowance=allowance):
                self.settings.is_enabled = is_enabled
                self.settings.daily_free_spins = allowance
                self.settings.save()
                state = self.state(self.now + timedelta(days=3))
                self.assertEqual(state.available_spins, 2)
                self.assertIsNone(state.next_spin_at)
