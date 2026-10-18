from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from game.models import Match, MatchEvent, MatchEventParticipant


@override_settings(NEUROKEFF_GAME_EVENTS_STALE_SECONDS=60)
class MatchEventsEndpointTests(TestCase):
    def setUp(self):
        self.match = Match.objects.create(
            external_id=930001,
            sync_scope=Match.SyncScope.LIVE,
            score="2:1",
            live_minute=63,
            live_minute_label="63",
            events_fetched_at=timezone.now(),
            events_available=True,
        )
        self.url = reverse("game:match_events", kwargs={"slug": self.match.slug})

    def create_event(self, *, key, minute, seq, event_type="goal"):
        return MatchEvent.objects.create(
            match=self.match,
            event_key=key,
            external_id=int(key.split(":")[-1]),
            seq=seq,
            event_type_code=event_type,
            event_type_name=event_type,
            event_type_name_ru="гол" if event_type == "goal" else "карточка",
            detail_code="regular",
            detail_name_ru="с игры",
            minute=minute,
            extra_minute=2 if minute == 45 else None,
            team_external_id=5101,
            team_name="Home",
            team_name_ru="Хозяева",
            team_side="home",
            player_external_id=7101,
            player_name="Player",
            player_name_ru="Игрок",
            assist_external_id=7102,
            assist_name="Assist",
            assist_name_ru="Ассистент",
            fetched_at=timezone.now(),
        )

    @patch("game.match_detail_views.refresh_match_events.apply_async")
    def test_missing_clock_uses_event_progress_in_endpoint_and_ssr_without_finishing_match(self, queue):
        self.match.live_minute = None
        self.match.live_minute_label = ""
        self.match.save(update_fields=["live_minute", "live_minute_label"])
        event = self.create_event(key="id:300010", minute=120, seq=1)
        event.extra_minute = 1
        event.save(update_fields=["extra_minute"])
        state = self.client.get(self.url).json()["match"]
        self.assertEqual(state["progress"], 100)
        self.assertEqual(state["scope"], "live")
        self.assertIsNone(state["minute"])
        self.assertEqual(state["timeline_label"], "")
        self.assertContains(self.client.get(self.match.get_absolute_url()), 'data-match-v2-progress="100"')
        self.match.refresh_from_db()
        self.assertEqual(self.match.sync_scope, "live")
        self.assertIsNone(self.match.live_minute)

    @patch("game.match_detail_views.refresh_match_events.apply_async")
    def test_missing_clock_progress_uses_latest_event_not_first_and_stays_zero_without_events(self, queue):
        self.match.live_minute = None
        self.match.live_minute_label = ""
        self.match.save(update_fields=["live_minute", "live_minute_label"])
        self.assertEqual(self.client.get(self.url).json()["match"]["progress"], 0)
        self.create_event(key="id:300011", minute=12, seq=1)
        self.create_event(key="id:300012", minute=45, seq=2)
        self.assertEqual(self.client.get(self.url).json()["match"]["progress"], 50)

    @patch("game.match_detail_views.refresh_match_events.apply_async")
    def test_known_clock_has_priority_over_events_and_prematch_never_advances(self, queue):
        self.create_event(key="id:300013", minute=120, seq=1)
        self.assertEqual(self.client.get(self.url).json()["match"]["progress"], 70)
        self.match.sync_scope = "prematch"
        self.match.live_minute = None
        self.match.save(update_fields=["sync_scope", "live_minute"])
        self.assertEqual(self.client.get(self.url).json()["match"]["progress"], 0)

    @patch("game.services.match_sync.MatchSyncService.sync_match_events")
    @patch("game.match_detail_views.refresh_match_events.apply_async")
    def test_returns_db_backed_match_state_events_and_participants(
        self,
        queue_refresh,
        sync_match_events,
    ):
        late = self.create_event(key="id:300002", minute=45, seq=2)
        early = self.create_event(
            key="id:300001",
            minute=12,
            seq=1,
            event_type="yellow_card",
        )
        MatchEventParticipant.objects.create(
            event=early,
            role="booked",
            player_external_id=7101,
            player_name="Player",
            player_name_ru="Игрок",
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-cache")
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["version"])
        self.assertEqual(payload["match"]["id"], self.match.pk)
        self.assertEqual(payload["match"]["external_id"], self.match.external_id)
        self.assertEqual(payload["match"]["scope"], Match.SyncScope.LIVE)
        self.assertEqual(payload["match"]["score"], {"display": "2:1", "home": "2", "away": "1"})
        self.assertEqual(payload["match"]["minute"], 63)
        self.assertEqual(payload["match"]["timeline_label"], "63′")
        self.assertTrue(payload["match"]["show_timeline"])
        self.assertGreater(payload["match"]["progress"], 0)
        self.assertEqual(
            payload["events_state"],
            {
                "status": "ready",
                "available": True,
                "empty": False,
                "stale": False,
                "fetched_at": self.match.events_fetched_at.isoformat(),
                "refresh_queued": False,
            },
        )
        self.assertEqual(
            [item["external_id"] for item in payload["events"]],
            [early.external_id, late.external_id],
        )
        first = payload["events"][0]
        self.assertEqual(first["type"]["code"], "yellow_card")
        self.assertEqual(
            first["presentation"],
            {"kind": "yellow-card", "icon": "▮", "side": "home"},
        )
        self.assertEqual(first["time"], {"minute": 12, "extra": None, "label": "12′"})
        self.assertEqual(first["team"]["side"], "home")
        self.assertEqual(first["player"]["name_ru"], "Игрок")
        self.assertEqual(first["assist"]["name_ru"], "Ассистент")
        self.assertEqual(first["participants"][0]["role"], "booked")
        queue_refresh.assert_not_called()
        sync_match_events.assert_not_called()

    @patch("game.match_detail_views.refresh_match_events.apply_async")
    def test_interrupted_match_keeps_server_rendered_timeline_after_ajax_refresh(self, queue_refresh):
        self.match.sync_scope = Match.SyncScope.INTERRUPTED
        self.match.save(update_fields=["sync_scope"])
        self.create_event(key="id:300020", minute=66, seq=1, event_type="substitution")

        page = self.client.get(self.match.get_absolute_url())
        payload = self.client.get(self.url).json()

        self.assertContains(page, 'data-match-timeline data-match-v2-progress="0"')
        self.assertNotContains(
            page,
            'data-match-timeline data-match-v2-progress="0" aria-label="Ход матча" hidden',
        )
        self.assertEqual(payload["match"]["scope"], Match.SyncScope.INTERRUPTED)
        self.assertTrue(payload["match"]["show_timeline"])
        queue_refresh.assert_not_called()

    @patch("game.services.match_sync.MatchSyncService.sync_match_events")
    @patch("game.match_detail_views.refresh_match_events.apply_async")
    @patch("game.match_detail_views.cache.add", return_value=True)
    def test_stale_response_only_queues_async_refresh(
        self,
        cache_add,
        queue_refresh,
        sync_match_events,
    ):
        self.match.events_fetched_at = timezone.now() - timedelta(minutes=2)
        self.match.save(update_fields=("events_fetched_at", "updated_at"))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["events_state"]["stale"])
        self.assertTrue(payload["events_state"]["refresh_queued"])
        cache_add.assert_called_once_with(
            f"match-events-queue:{self.match.pk}",
            "1",
            timeout=120,
        )
        queue_refresh.assert_called_once_with(args=[self.match.pk], retry=False)
        sync_match_events.assert_not_called()

    @patch("game.match_detail_views.cache.delete")
    @patch(
        "game.match_detail_views.refresh_match_events.apply_async",
        side_effect=RuntimeError("broker unavailable"),
    )
    @patch("game.match_detail_views.cache.add", return_value=True)
    def test_queue_failure_does_not_break_endpoint(
        self,
        cache_add,
        queue_refresh,
        cache_delete,
    ):
        self.match.events_fetched_at = timezone.now() - timedelta(minutes=2)
        self.match.save(update_fields=("events_fetched_at", "updated_at"))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["events_state"]["refresh_queued"])
        cache_delete.assert_called_once_with(f"match-events-queue:{self.match.pk}")

    @patch("game.match_detail_views.refresh_match_events.apply_async")
    def test_pending_prematch_does_not_queue_refresh(self, queue_refresh):
        self.match.sync_scope = Match.SyncScope.PREMATCH
        self.match.events_fetched_at = None
        self.match.events_available = None
        self.match.save(
            update_fields=(
                "sync_scope",
                "events_fetched_at",
                "events_available",
                "updated_at",
            )
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events_state"]["status"], "pending")
        self.assertFalse(response.json()["events_state"]["stale"])
        self.assertFalse(response.json()["events_state"]["refresh_queued"])
        queue_refresh.assert_not_called()

    def test_empty_and_unavailable_states_are_distinct(self):
        response = self.client.get(self.url)
        self.assertEqual(response.json()["events_state"]["status"], "empty")
        self.assertTrue(response.json()["events_state"]["empty"])

        known_event = self.create_event(key="id:300003", minute=70, seq=3)
        self.match.events_available = False
        self.match.events_fetched_at = timezone.now()
        self.match.save(
            update_fields=("events_available", "events_fetched_at", "updated_at")
        )

        response = self.client.get(self.url)

        payload = response.json()
        self.assertEqual(payload["events_state"]["status"], "unavailable")
        self.assertFalse(payload["events_state"]["empty"])
        self.assertEqual(payload["events"][0]["external_id"], known_event.external_id)

    def test_version_changes_when_event_changes(self):
        event = self.create_event(key="id:300004", minute=22, seq=4)
        first_version = self.client.get(self.url).json()["version"]
        event.player_name = "Updated Player"
        event.save(update_fields=("player_name", "updated_at"))

        second_version = self.client.get(self.url).json()["version"]

        self.assertNotEqual(first_version, second_version)

    def test_only_get_is_allowed_and_unknown_match_is_404(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)
        missing_url = reverse("game:match_events", kwargs={"slug": "missing-match"})
        self.assertEqual(self.client.get(missing_url).status_code, 404)
