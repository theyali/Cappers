from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from notifications.models import MatchWatch

from .models import Match


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
            "match-watch-button match-card-watch-button match-detail-watch-button is-watching",
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
        self.assertContains(response, "data-match-predictions-feed")
        self.assertContains(response, "data-match-predictions-block")
        self.assertContains(response, "data-skeleton-block")
        self.assertContains(response, "front/js/prediction-reactions.js")
        self.assertContains(response, "front/js/match-predictions.js")
