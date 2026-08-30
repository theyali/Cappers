import json

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from front.match_table_views import MAX_TABLE_ODDS_BATCH, _match_ids, match_table_odds


class MatchTableOddsTests(SimpleTestCase):
    def test_match_ids_are_unique_valid_and_bounded(self):
        raw = ",".join(["1", "1", "bad", "0"] + [str(value) for value in range(2, 60)])

        result = _match_ids(raw)

        self.assertEqual(len(result), MAX_TABLE_ODDS_BATCH)
        self.assertEqual(result[0], 1)
        self.assertEqual(result[1], 2)
        self.assertEqual(len(result), len(set(result)))
        self.assertNotIn(0, result)

    def test_empty_odds_request_does_not_touch_database(self):
        request = RequestFactory().get(reverse("front:match_table_odds"))
        request.user = AnonymousUser()

        response = match_table_odds(request)
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, {"ok": True, "items": {}})
