from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from game.models import Country, Match, MatchOdds, Sport
from game.services.match_sync import MatchSyncService


@override_settings(LOCAL_LOGO_DOWNLOAD_ENABLED=False,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class MatchSyncConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.sport = Sport.objects.create(external_id=2, code="football", name="Football")
        for pk in (11, 12):
            Country.objects.create(external_id=pk, name=f"Country {pk}")
        self.payloads = [{
            "id": pk, "sport_id": 2, "time_status": "1", "score": "1-0",
            "league": {"country": {"id": country, "name": {"en": f"Country {country}"}}},
            "venue": {"id": pk, "name": {"en": f"Venue {pk}"}},
            "teams": {"home": {"id": pk * 2, "name": {"en": f"Home {pk}"}},
                      "away": {"id": pk * 2 + 1, "name": {"en": f"Away {pk}"}}},
            "odds": {"home_win_bet": 1.9},
        } for pk, country in ((501, 11), (502, 12))]

    def service(self, payloads=None):
        provider = Mock()
        provider.fetch_matches_info.return_value = payloads or deepcopy(self.payloads)
        service = MatchSyncService(provider=provider)
        service._sport_cache[("id", 2)] = Sport.objects.get(pk=self.sport.pk)
        return service

    def test_each_match_commits_before_the_next_and_its_own_addons_roll_back_together(self):
        service = self.service()
        sync_odds = service._sync_odds

        def fail_second(match, *args, **kwargs):
            sync_odds(match, *args, **kwargs)
            if match.external_id == 502:
                raise RuntimeError("second match failed")

        with patch.object(service, "_sync_odds", side_effect=fail_second):
            with self.assertRaisesMessage(RuntimeError, "second match failed"):
                service._sync_scope("live", self.payloads)
        first = Match.objects.get(external_id=501)
        self.assertTrue(MatchOdds.objects.filter(match=first, home_win_bet=1.9).exists())
        self.assertFalse(Match.objects.filter(external_id=502).exists())

    def test_reference_updates_are_outside_match_transactions_in_both_sync_paths(self):
        service = self.service()
        defaults = service._match_defaults
        observed = []

        def prepare(*args, **kwargs):
            observed.append(connection.in_atomic_block)
            return defaults(*args, **kwargs)

        with patch.object(service, "_match_defaults", side_effect=prepare):
            service._sync_scope("live", self.payloads, state_only=True)
            Match.objects.update(last_seen_at=timezone.now() - timedelta(hours=1))
            service.sync_stuck_live_matches()
        self.assertEqual(observed, [False, False, False, False])

    def run_sync(self, payloads, barrier, *, stuck=False):
        close_old_connections()
        try:
            service = self.service(payloads)
            prepare = service._match_defaults
            first = True

            def synchronize(*args, **kwargs):
                nonlocal first
                wait = first
                first = False
                if wait and stuck:
                    barrier.wait(timeout=10)
                result = prepare(*args, **kwargs)
                if wait and not stuck:
                    barrier.wait(timeout=10)
                return result

            with patch.object(service, "_match_defaults", side_effect=synchronize):
                if stuck:
                    return service.sync_stuck_live_matches()
                return service._sync_scope("live", payloads, state_only=True)
        finally:
            close_old_connections()

    @skipUnless(connection.vendor == "postgresql", "Row-lock regression requires PostgreSQL")
    def test_opposite_provider_order_does_not_deadlock_reference_rows(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.run_sync, deepcopy(payloads), barrier)
                       for payloads in (self.payloads, list(reversed(self.payloads)))]
            results = [future.result(timeout=25) for future in futures]
        self.assertTrue(all(result["status"] == "ok" for result in results))
        self.assertEqual(Match.objects.count(), 2)

    @skipUnless(connection.vendor == "postgresql", "Row-lock regression requires PostgreSQL")
    def test_stuck_reconciliation_and_polling_do_not_invert_match_and_reference_locks(self):
        Match.objects.create(external_id=501, sport=self.sport, sync_scope="live",
            last_seen_at=timezone.now() - timedelta(hours=1))
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            polling = executor.submit(self.run_sync, self.payloads[:1], barrier)
            stuck = executor.submit(self.run_sync, self.payloads[:1], barrier, stuck=True)
            results = [polling.result(timeout=25), stuck.result(timeout=25)]
        self.assertTrue(all(result["updated"] == 1 for result in results))
        self.assertEqual(Match.objects.get(external_id=501).score, "1-0")
