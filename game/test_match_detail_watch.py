from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from notifications.models import MatchWatch

from .models import Match, MatchEvent


class MatchDetailWatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="detail-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.match = Match.objects.create(
            external_id=990001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=2),
        )
        self.client.force_login(self.user)

    def test_match_detail_uses_bookmark_instead_of_text_watch_control(self):
        MatchWatch.objects.create(user=self.user, match=self.match)

        response = self.client.get(self.match.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "match-watch-button match-card-watch-button match-detail-watch-button "
            "match-v2-icon-button is-watching",
        )
        self.assertContains(response, "data-match-watch-toggle")
        self.assertContains(
            response,
            reverse("notifications:match_watch", kwargs={"match_id": self.match.id}),
        )
        self.assertNotContains(response, ">Матч отслеживается</button>", html=False)

    def test_match_detail_loads_prediction_feed_and_reaction_scripts(self):
        response = self.client.get(self.match.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        events_url = reverse("game:match_events", kwargs={"slug": self.match.slug})
        self.assertContains(
            response,
            f'data-events-url="{events_url}"',
        )
        self.assertContains(response, "data-match-predictions-feed")
        self.assertContains(response, "data-match-predictions-block")
        self.assertContains(response, "data-skeleton-block")
        self.assertContains(response, "front/js/prediction-reactions")
        self.assertContains(response, "front/js/match-predictions")
        self.assertContains(response, "front/js/match-detail-v2")
        self.assertContains(response, "data-match-events-panel")
        self.assertContains(response, "data-match-events-list")
        self.assertContains(response, "data-match-events-retry")
        self.assertContains(response, "data-match-events-announcer")

    def test_match_detail_renders_db_events_before_javascript_loads(self):
        self.match.sync_scope = Match.SyncScope.LIVE
        self.match.score = "1:0"
        self.match.live_minute = 24
        self.match.events_fetched_at = timezone.now()
        self.match.events_available = True
        self.match.save(
            update_fields=(
                "sync_scope",
                "score",
                "live_minute",
                "events_fetched_at",
                "events_available",
                "updated_at",
            )
        )
        MatchEvent.objects.create(
            match=self.match,
            event_key="id:990101",
            external_id=990101,
            seq=1,
            event_type_code="goal",
            event_type_name_ru="Гол",
            minute=24,
            team_side="home",
            player_name_ru="Тестовый игрок",
            fetched_at=timezone.now(),
        )

        response = self.client.get(self.match.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-events-state="ready"')
        self.assertContains(response, 'data-event-key="id:990101"')
        self.assertContains(response, "Тестовый игрок")
        self.assertContains(response, "24′")
        self.assertContains(response, "is-home is-goal")
