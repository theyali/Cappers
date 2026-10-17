from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from game.models import ComparisonBookmaker, Match, MatchOddsSnapshot, MatchBookmakerOdds, Sport
from game.services.odds_comparison import build_match_odds_comparison_ui


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class MatchOddsComparisonEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        sport = Sport.objects.create(code="football", name="Football")
        self.match = Match.objects.create(external_id=940001, sport=sport, sync_scope="prematch", starts_at=timezone.now() + timedelta(hours=2))
        now = timezone.now()
        self.snapshot = MatchOddsSnapshot.objects.create(match=self.match, scope="prematch", available=True,
            provider_updated_at=now, fetched_at=now, requested_at=now)
        for index, price in enumerate((1.91, 2.05)):
            MatchBookmakerOdds.objects.create(snapshot=self.snapshot, bookmaker_key=str(index), name=f"BK {index}", markets=[{
                "name": "Match Winner", "key": "three_way", "period": "full_time", "line": None,
                "outcomes": [{"name": "Home", "key": "home", "odds": price, "line": None}],
            }])
        self.url = reverse("game:match_odds_comparison", kwargs={"slug": self.match.slug})

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    @patch("game.services.match_sync.MatchSyncService.sync_match_bookmaker_odds")
    def test_fresh_endpoint_is_db_backed_and_marks_best(self, sync, queue):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-cache")
        data = response.json()
        self.assertTrue(data["visible"])
        self.assertEqual(data["status"], "ready")
        self.assertIn('class="is-best"', data["html"])
        self.assertIn("2.05", data["html"])
        self.assertTrue(data["expires_at"])
        self.assertFalse(data["refresh_queued"])
        queue.assert_not_called()
        sync.assert_not_called()

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    def test_stale_data_is_not_best_and_queue_is_deduplicated(self, queue):
        self.snapshot.fetched_at = timezone.now() - timedelta(hours=2)
        self.snapshot.save(update_fields=["fetched_at"])
        first = self.client.get(self.url).json()
        second = self.client.get(self.url).json()
        self.assertEqual(first["status"], "stale")
        self.assertNotIn('class="is-best"', first["html"])
        self.assertTrue(first["refresh_queued"])
        self.assertFalse(second["refresh_queued"])
        queue.assert_called_once_with(args=[self.match.pk], retry=False)

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async", side_effect=RuntimeError("broker unavailable"))
    def test_missing_data_and_broker_failure_do_not_break_page(self, queue):
        self.snapshot.delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["visible"])
        self.assertFalse(response.json()["refresh_queued"])
        self.assertIsNone(cache.get(f"match-odds-comparison-queue:{self.match.pk}"))

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    def test_finished_match_is_archived_without_refresh(self, queue):
        self.match.sync_scope = "finished"
        self.match.save(update_fields=["sync_scope"])
        data = self.client.get(self.url).json()
        self.assertEqual(data["status"], "finished")
        self.assertIn('class="is-best"', data["html"])
        self.assertTrue(data["archived"])
        self.assertIn("Архив предматчевой линии", data["sidebar_html"])
        self.assertIn("2.05", data["sidebar_html"])
        self.assertFalse(data["expires_at"])
        queue.assert_not_called()

    def test_version_changes_when_best_price_changes(self):
        first = self.client.get(self.url).json()["version"]
        book = self.snapshot.bookmakers.get(bookmaker_key="0")
        book.markets[0]["outcomes"][0]["odds"] = 2.5
        book.save(update_fields=["markets"])
        self.assertNotEqual(first, self.client.get(self.url).json()["version"])

    def test_finished_archive_remains_ranked_when_old_and_is_in_page_sidebar(self):
        self.match.sync_scope = "finished"
        self.match.save(update_fields=["sync_scope"])
        self.snapshot.provider_updated_at -= timedelta(days=3)
        self.snapshot.fetched_at -= timedelta(days=3)
        self.snapshot.save(update_fields=["provider_updated_at", "fetched_at"])
        data = self.client.get(self.url).json()
        self.assertTrue(data["archived"])
        self.assertIn('class="is-best"', data["html"])
        self.assertIn("не текущие предложения", data["sidebar_html"])
        html = self.client.get(self.match.get_absolute_url()).content.decode()
        main, sidebar = html.split('<aside class="match-v2-side"', 1)
        self.assertNotIn("Лучшие по рынкам", main)
        self.assertIn("Лучшие по рынкам", sidebar)

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    def test_finished_without_prematch_never_substitutes_live_and_queues_recovery(self, queue):
        self.match.sync_scope = "finished"
        self.match.save(update_fields=["sync_scope"])
        self.snapshot.scope = "live"
        self.snapshot.save(update_fields=["scope"])
        data = self.client.get(self.url).json()
        self.assertTrue(data["archived"])
        self.assertFalse(data["visible"])
        self.assertNotIn("Архив live-линии", data["sidebar_html"])
        self.assertNotIn('class="is-best"', data["html"])
        self.assertTrue(data["refresh_queued"])
        queue.assert_called_once_with(args=[self.match.pk], retry=False)

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    def test_live_page_and_ajax_keep_old_prematch_comparison_and_do_not_use_live(self, queue):
        self.match.sync_scope = "live"
        self.match.starts_at = timezone.now() - timedelta(hours=1)
        self.match.save(update_fields=["sync_scope", "starts_at"])
        self.snapshot.provider_updated_at -= timedelta(days=3)
        self.snapshot.save(update_fields=["provider_updated_at"])
        live = MatchOddsSnapshot.objects.create(match=self.match, scope="live", available=True,
            fetched_at=timezone.now(), requested_at=timezone.now(), provider_updated_at=timezone.now())
        MatchBookmakerOdds.objects.create(snapshot=live, bookmaker_key="live", name="Live BK",
            markets=self.snapshot.bookmakers.first().markets)
        data = self.client.get(self.url).json()
        self.assertEqual(data["status"], "archived")
        self.assertTrue(data["archived"])
        self.assertTrue(data["visible"])
        self.assertIn("Архив предматчевой линии", data["sidebar_html"])
        self.assertIn("2.05", data["html"])
        self.assertNotIn("Live BK", data["html"])
        self.assertFalse(data["expires_at"])
        self.assertFalse(data["refresh_queued"])
        html = self.client.get(self.match.get_absolute_url()).content.decode()
        self.assertIn("Архив предматчевой линии", html)
        self.assertNotIn("Live BK", html)
        queue.assert_not_called()

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    def test_live_archive_is_visible_while_final_prematch_check_is_queued(self, queue):
        self.match.sync_scope = "live"
        self.match.starts_at = timezone.now() - timedelta(hours=1)
        self.match.save(update_fields=["sync_scope", "starts_at"])
        self.snapshot.fetched_at = timezone.now() - timedelta(hours=2)
        self.snapshot.save(update_fields=["fetched_at"])
        data = self.client.get(self.url).json()
        self.assertTrue(data["visible"])
        self.assertTrue(data["archived"])
        self.assertIn("2.05", data["html"])
        self.assertTrue(data["refresh_queued"])
        self.assertTrue(data["archive_needs_refresh"])
        pending = self.client.get(self.url).json()
        self.assertFalse(pending["refresh_queued"])
        self.assertTrue(pending["archive_needs_refresh"])
        queue.assert_called_once_with(args=[self.match.pk], retry=False)
        self.snapshot.fetched_at = timezone.now()
        self.snapshot.save(update_fields=["fetched_at"])
        self.assertFalse(self.client.get(self.url).json()["archive_needs_refresh"])

    def test_registry_icons_and_renamed_brands_render_in_table_and_summary(self):
        first = self.client.get(self.url).json()["version"]
        brand = ComparisonBookmaker.objects.create(name="BK 1", icon="game/bookmakers/bk1.png")
        brand.name = "Название из админки"
        brand.save()
        data = self.client.get(self.url).json()
        self.assertNotEqual(first, data["version"])
        self.assertIn("Название из админки", data["html"])
        self.assertIn("game/bookmakers/bk1.png", data["html"])
        self.assertNotIn("Лучшие по рынкам", data["html"])
        self.assertIn("Лучшие по рынкам", data["sidebar_html"])
        self.assertIn("Название из админки", data["sidebar_html"])
        section = build_match_odds_comparison_ui(self.match)["sections"][0]
        self.assertEqual(section["rows"][0]["winner_brands"][0]["name"], brand.name)
        self.assertTrue(section["has_best"])

    def test_tied_best_shows_all_winners_and_stale_summary_has_no_winners(self):
        book = self.snapshot.bookmakers.get(bookmaker_key="0")
        book.markets[0]["outcomes"][0]["odds"] = 2.05
        book.save(update_fields=["markets"])
        section = build_match_odds_comparison_ui(self.match)["sections"][0]
        self.assertEqual(len(section["rows"][0]["winner_brands"]), 2)
        self.assertEqual(sum(cell["is_best"] for cell in section["rows"][0]["cells"]), 2)
        self.snapshot.fetched_at -= timedelta(hours=2)
        self.snapshot.save(update_fields=["fetched_at"])
        section = build_match_odds_comparison_ui(self.match)["sections"][0]
        self.assertFalse(section["has_best"])
        self.assertEqual(section["rows"][0]["winner_brands"], [])

    def test_featured_sidebar_caps_tied_bookmakers_at_three_without_hiding_table_winners(self):
        for index in range(2, 6):
            source = self.snapshot.bookmakers.get(bookmaker_key="1")
            MatchBookmakerOdds.objects.create(snapshot=self.snapshot, bookmaker_key=str(index),
                name=f"BK {index}", markets=source.markets)
        section = build_match_odds_comparison_ui(self.match)["sections"][0]
        featured = section["featured_offers"]
        self.assertEqual(len(featured), 3)
        self.assertEqual(len({offer["bookmaker"]["key"] for offer in featured}), 3)
        self.assertTrue(all(offer["advantage"] == "Один из лучших коэффициентов" for offer in featured))
        self.assertEqual(sum(cell["is_best"] for cell in section["rows"][0]["cells"]), 5)
        sidebar = self.client.get(self.url).json()["sidebar_html"]
        self.assertEqual(sidebar.count('class="match-comparison-featured"'), 3)
        self.assertIn("Все букмекеры", sidebar)

    def test_featured_advantage_uses_next_same_outcome_price(self):
        section = build_match_odds_comparison_ui(self.match)["sections"][0]
        self.assertEqual(len(section["featured_offers"]), 1)
        offer = section["featured_offers"][0]
        self.assertEqual(offer["bookmaker"]["name"], "BK 1")
        self.assertEqual(offer["coefficient"], "2.05")
        self.assertEqual(offer["advantage"], "на 7,3% выше, чем у BK 0")
        self.assertEqual(offer["row_index"], 0)
        self.snapshot.fetched_at -= timedelta(days=1)
        self.snapshot.save(update_fields=["fetched_at"])
        self.assertEqual(build_match_odds_comparison_ui(self.match)["sections"][0]["featured_offers"], [])

    def test_featured_selects_one_offer_per_brand_by_relative_edge(self):
        self.snapshot.bookmakers.all().delete()
        for index, prices in enumerate(((2, 2, 2), (2, 2, 2), (4, 2, 2), (2, 6, 2), (2, 2, 8))):
            MatchBookmakerOdds.objects.create(snapshot=self.snapshot, bookmaker_key=str(index), name=f"BK {index}",
                markets=[{"name": "Match Winner", "key": "three_way", "period": "full_time", "line": None,
                    "outcomes": [{"name": label, "key": key, "odds": price, "line": None}
                        for label, key, price in zip(("Home", "Draw", "Away"), ("home", "draw", "away"), prices)]},
                    {"name": "First Half Winner", "key": "three_way", "period": "first_half", "line": None,
                     "outcomes": [{"name": "Home", "key": "home", "odds": 12 if index == 4 else 2, "line": None}]}])
        offers = build_match_odds_comparison_ui(self.match)["sections"][0]["featured_offers"]
        self.assertEqual([offer["bookmaker"]["name"] for offer in offers], ["BK 4", "BK 3", "BK 2"])
        self.assertEqual(offers[0]["advantage"], "на 500% выше, чем у BK 0")
        self.assertEqual(offers[0]["row_index"], 3)

    def test_registry_has_own_game_admin_and_stable_key(self):
        from django.contrib import admin
        from back.models import Bookmaker
        brand = ComparisonBookmaker.objects.create(name="  BK  1 ")
        self.assertEqual(brand.key, "bk 1")
        self.assertEqual(brand._meta.app_label, "game")
        self.assertIsNot(ComparisonBookmaker, Bookmaker)
        self.assertIn(ComparisonBookmaker, admin.site._registry)
        self.assertEqual(reverse("admin:game_comparisonbookmaker_changelist"), "/admin/game/comparisonbookmaker/")

    def test_admin_uploads_icon_and_rejects_duplicate_brand(self):
        import base64
        from tempfile import TemporaryDirectory
        from django.contrib.auth import get_user_model
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(get_user_model().objects.create_superuser(
            username="bookmaker-admin", password="test-password",
        ))
        url = reverse("admin:game_comparisonbookmaker_add")
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            icon = SimpleUploadedFile("bk.gif", base64.b64decode(
                "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
            ), content_type="image/gif")
            response = self.client.post(url, {"name": "BK 1", "icon": icon, "_save": "Сохранить"})
            self.assertEqual(response.status_code, 302)
            brand = ComparisonBookmaker.objects.get(key="bk 1")
            self.assertTrue(brand.icon.storage.exists(brand.icon.name))
            self.assertTrue(brand.icon.name.startswith("game/bookmakers/"))
            response = self.client.post(url, {"name": "  bk  1 ", "_save": "Сохранить"})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Этот букмекер уже есть")
            self.assertEqual(ComparisonBookmaker.objects.count(), 1)

    def test_bookmaker_names_are_escaped(self):
        self.snapshot.bookmakers.filter(bookmaker_key="0").update(name='<script>alert("bad")</script>')
        html = self.client.get(self.url).json()["html"]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_table_columns_are_unique_brands_and_precision_is_preserved(self):
        book = self.snapshot.bookmakers.get(bookmaker_key="1")
        book.markets[0]["outcomes"][0]["odds"] = "2.005"
        book.save(update_fields=["markets"])
        MatchBookmakerOdds.objects.create(snapshot=self.snapshot, bookmaker_key="duplicate",
            name=book.name, markets=book.markets)
        table = build_match_odds_comparison_ui(self.match)["sections"][0]
        self.assertEqual(len(table["columns"]), 2)
        self.assertEqual(table["rows"][0]["best"], "2.005")

    def test_get_only_and_not_found(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)
        self.assertEqual(self.client.get(reverse("game:match_odds_comparison", kwargs={"slug": "missing-match"})).status_code, 404)

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    def test_ssr_comparison_has_no_bet_controls_or_fake_sidebar_best(self, queue):
        response = self.client.get(self.match.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сравнение коэффициентов")
        self.assertContains(response, "data-match-comparison")
        self.assertContains(response, "match-odds-comparison")
        self.assertNotContains(response, '<section class="match-v2-side-card" aria-label="Лучший коэффициент">')
        self.assertNotContains(response, '<em>Лучший</em>')
        html = response.content.decode()
        table = html.split('id="match-comparison"', 1)[1].split('id="match-predictions"', 1)[0]
        self.assertNotIn("data-bet-option", table)

    @patch("game.tasks.refresh_match_bookmaker_odds.apply_async")
    def test_comparison_navigation_tab_is_visible_only_with_data(self, queue):
        response = self.client.get(self.match.get_absolute_url())
        self.assertContains(response, '<a href="#match-comparison" data-comparison-tab>Сравнение КФ</a>', html=True)
        self.snapshot.delete()
        response = self.client.get(self.match.get_absolute_url())
        self.assertContains(response, '<a href="#match-comparison" data-comparison-tab hidden>Сравнение КФ</a>', html=True)
