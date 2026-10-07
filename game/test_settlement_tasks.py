from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from game import tasks


class SettlementTaskTests(SimpleTestCase):
    def setUp(self):
        cache.delete("settlement:finished")
        cache.delete("settlement:live")

    def tearDown(self):
        cache.delete("settlement:finished")
        cache.delete("settlement:live")

    def test_settlement_runs_one_at_a_time(self):
        cache.add("settlement:finished", "1", timeout=60)

        with patch("game.tasks.settle_finished_matches") as settle:
            result = tasks.settle_predictions()

        settle.assert_not_called()
        self.assertEqual(result["reason"], "already_running")

    def test_lock_is_released_after_settlement(self):
        with patch("game.tasks.settle_finished_matches", return_value={"matches": 0}):
            self.assertEqual(tasks.settle_predictions(), {"matches": 0})

        self.assertIsNone(cache.get("settlement:finished"))

    def test_finished_sync_queues_settlement_instead_of_running_it(self):
        with (
            patch("game.tasks.MatchSyncService") as service,
            patch("game.tasks.settle_finished_matches") as settle,
            patch.object(tasks.settle_predictions, "delay") as delay,
        ):
            service.return_value.sync_finished.return_value = {"status": "ok"}
            result = tasks._sync_finished_sport("football")

        settle.assert_not_called()
        delay.assert_called_once_with()
        self.assertEqual(result["settlement"], "queued")

    def test_live_sync_tasks_share_one_live_settlement(self):
        cache.add("settlement:live", "1", timeout=60)

        with (
            patch("game.tasks.MatchSyncService") as service,
            patch("game.tasks.settle_live_matches") as settle_live,
        ):
            service.return_value.sync_live.return_value = {"status": "ok"}
            result = tasks._sync_live_sport("football")

        settle_live.assert_not_called()
        self.assertEqual(result["settlement"]["reason"], "already_running")

    @override_settings(NEUROKEFF_MATCH_SYNC_LOCK_SECONDS=600, CELERY_TASK_TIME_LIMIT=300)
    def test_lock_does_not_outlive_the_task_time_limit(self):
        self.assertEqual(tasks._lock_seconds(), 300)
