from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from game.models import Match
from game.services.coupon_validation import verify_matches_for_coupon


class FakeCouponInfoProvider:
    def __init__(self, payloads):
        self.payloads = payloads
        self.requested_ids = []

    def fetch_matches_info(self, ids):
        self.requested_ids.append(list(ids))
        return self.payloads

    def fetch_matches_for_scope(self, *args, **kwargs):
        raise AssertionError("Coupon validation must not scan scope lists")


class CouponValidationTests(TestCase):
    @override_settings(
        COUPON_MATCH_STALE_SECONDS=60,
        COUPON_MATCH_STATE_CACHE_SECONDS=1,
    )
    def test_stale_matches_are_verified_by_exact_info_batch(self):
        first = Match.objects.create(
            external_id=930001,
            sync_scope=Match.SyncScope.PREMATCH,
            last_seen_at=timezone.now() - timedelta(minutes=5),
        )
        second = Match.objects.create(
            external_id=930002,
            sync_scope=Match.SyncScope.PREMATCH,
            last_seen_at=timezone.now() - timedelta(minutes=5),
        )
        provider = FakeCouponInfoProvider(
            [
                {"id": first.external_id, "time_status": "0"},
                {"id": second.external_id, "time_status": "0"},
            ]
        )

        with patch(
            "game.services.coupon_validation.NeurokeffSportsProvider",
            return_value=provider,
        ):
            summary = verify_matches_for_coupon([first, second])

        self.assertTrue(summary.remote_checked)
        self.assertFalse(summary.cache_used)
        self.assertEqual(provider.requested_ids, [[first.external_id, second.external_id]])

    @override_settings(COUPON_MATCH_STALE_SECONDS=60)
    def test_stale_started_match_blocks_coupon(self):
        match = Match.objects.create(
            external_id=930003,
            sync_scope=Match.SyncScope.PREMATCH,
            last_seen_at=timezone.now() - timedelta(minutes=5),
        )
        provider = FakeCouponInfoProvider(
            [{"id": match.external_id, "time_status": "1"}]
        )

        with patch(
            "game.services.coupon_validation.NeurokeffSportsProvider",
            return_value=provider,
        ):
            with self.assertRaises(ValidationError):
                verify_matches_for_coupon([match])

        match.refresh_from_db()
        self.assertEqual(match.sync_scope, Match.SyncScope.LIVE)
