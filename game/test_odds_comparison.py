from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from game.models import Match, MatchBookmakerOdds, MatchOddsSnapshot, Sport
from game.services.odds_comparison import (
    normalize_bookmaker_markets,
    build_match_comparison_groups,
    build_match_odds_comparison,
)


def market(name="Goals Over/Under", label="Over 2.5", price="1.91", **extra):
    return {"id": 5, "raw_key": "5", "key": "total", "name": name,
            "period": "full_time", "line": "1.5", "team": None, "suspended": False,
            "outcomes": [{"key": "over", "name": label, "raw_name": label,
                          "line": "2.5", "odds": price, "suspended": False}], **extra}


def normalize(markets, **extra):
    return normalize_bookmaker_markets(markets, match_id=42, sport_code="football", scope="prematch", **extra)


class ComparisonNormalizationTests(SimpleTestCase):
    def test_decimal_aliases_produce_same_key_and_exact_price(self):
        first = market(price="1.9100")
        second = market(label="Over 2,500", price=2.05)
        second["outcomes"][0]["line"] = "+2.500"
        a, _ = normalize([first])
        b, _ = normalize([second])
        self.assertEqual(a[0]["comparison_key"], b[0]["comparison_key"])
        self.assertEqual(a[0]["line"], "2.5")
        self.assertEqual(Decimal(a[0]["coefficient"]), Decimal("1.91"))

    def test_individual_totals_and_periods_never_merge_with_match_total(self):
        inputs = [market(), market(name="Total - Home"), market(name="Total - Away"),
                  market(name="Goals Over/Under First Half", period="first_half"),
                  market(name="Goals Over/Under - Second Half", period="second_half")]
        offers, _ = normalize(inputs)
        self.assertEqual(len({o["comparison_key"] for o in offers}), 5)
        self.assertEqual([o["team"] for o in offers[:3]], ["match", "home", "away"])

    def test_all_outcome_lines_are_kept_not_just_first_market_line(self):
        source = market()
        extra = deepcopy(source["outcomes"][0])
        extra.update(name="Over 3.5", raw_name="Over 3.5", line="3.5")
        source["outcomes"].append(extra)
        offers, _ = normalize([source])
        self.assertEqual({o["line"] for o in offers}, {"2.5", "3.5"})

    def test_unsupported_markets_do_not_inherit_broad_provider_key(self):
        for name in ("Total Corners", "Total Shots", "Result/Total Goals", "1x2 - 30 minutes", "Home/Away", "Draw No Bet", "Mystery Total"):
            with self.subTest(name=name):
                offers, report = normalize([market(name=name)])
                self.assertEqual(offers, [])
                self.assertEqual(report["skipped"], {"unsupported_market": 1})

    def test_conflicting_team_or_period_is_rejected(self):
        for source in (market(name="Total - Home", team="away"), market(period="first_half")):
            offers, report = normalize([source])
            self.assertEqual(offers, [])
            self.assertIn("conflicting_context", report["skipped"])

    def test_asian_and_european_handicaps_have_different_keys(self):
        sources = []
        for name in ("Asian Handicap", "Handicap Result"):
            source = market(name=name, label="Away -1", line="-1")
            source["outcomes"][0]["line"] = "-1"
            sources.append(source)
        offers, _ = normalize(sources)
        self.assertEqual(len({o["comparison_key"] for o in offers}), 2)
        self.assertEqual({o["settlement"] for o in offers}, {"asian", "european"})
        self.assertTrue(all(o["line_reference"] == "home" for o in offers))
        self.assertTrue(all(o["line"] == "-1" and o["selection"] == "away" for o in offers))

    def test_invalid_handicap_draw_and_fractional_european_are_rejected(self):
        for name, label, line in (("Asian Handicap", "Draw -1", "-1"), ("Handicap Result", "Home -1.5", "-1.5")):
            source = market(name=name, label=label)
            source["outcomes"][0]["line"] = line
            self.assertEqual(normalize([source])[0], [])

    def test_conflicting_outcome_line_and_text_is_rejected(self):
        source = market(label="Over 3.5")
        self.assertEqual(normalize([source])[0], [])

    def test_suspended_and_invalid_prices_are_not_comparable(self):
        for price in (None, "NaN", "Infinity", "-1", "0", "1", "bad"):
            with self.subTest(price=price):
                self.assertEqual(normalize([market(price=price)])[0], [])
        source = market()
        source["outcomes"][0]["suspended"] = True
        self.assertEqual(normalize([source])[1]["skipped"], {"suspended": 1})
        source = market(suspended=True)
        self.assertEqual(normalize([source])[0], [])

    def test_conflicting_duplicate_price_is_excluded_and_equal_duplicate_is_deduplicated(self):
        a, b = market(), market(price="2.05")
        self.assertEqual(normalize([a, b])[0], [])
        self.assertEqual(normalize([a, b])[1]["skipped"], {"conflicting_duplicate": 1})
        self.assertEqual(len(normalize([a, deepcopy(a)])[0]), 1)

    def test_scope_and_match_are_part_of_identity(self):
        keys = []
        for match_id, scope in ((1, "prematch"), (1, "live"), (2, "prematch")):
            offers, _ = normalize_bookmaker_markets([market()], match_id=match_id, sport_code="football", scope=scope)
            keys.append(offers[0]["comparison_key"])
        self.assertEqual(len(set(keys)), 3)

    def test_unaudited_sport_is_not_guessed_and_source_is_not_mutated(self):
        source = [market()]
        before = deepcopy(source)
        offers, report = normalize_bookmaker_markets(source, match_id=1, sport_code="hockey", scope="prematch")
        self.assertEqual(offers, [])
        self.assertEqual(report["skipped"], {"unaudited_sport": 1})
        normalize(source)
        self.assertEqual(source, before)

    def test_core_outcome_types(self):
        for name, label, expected in (("Match Winner", "Home", "1"), ("Double Chance", "Home/Draw", "1X"),
                                      ("Both Teams Score", "Yes", "yes"), ("Exact Score", "2:1", "2:1")):
            source = market(name=name, label=label, line=None)
            source["outcomes"][0]["line"] = None
            with self.subTest(name=name):
                self.assertEqual(normalize([source])[0][0]["selection"], expected)


class ComparisonGroupingTests(TestCase):
    def setUp(self):
        sport = Sport.objects.create(code="football", name="Football")
        self.match = Match.objects.create(external_id=920042, sport=sport)
        now = timezone.now()
        self.snapshot = MatchOddsSnapshot.objects.create(match=self.match, scope="prematch", available=True, requested_at=now, fetched_at=now)
        for index, price in enumerate(("1.91", "2.05")):
            MatchBookmakerOdds.objects.create(snapshot=self.snapshot, bookmaker_key=str(index), name=f"BK {index}", markets=[market(price=price)])

    def test_same_outcome_from_different_bookmakers_is_one_group(self):
        groups = build_match_comparison_groups(self.match)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["offers"]), 2)
        self.assertEqual({o["coefficient"] for o in groups[0]["offers"]}, {"1.91", "2.05"})

    def test_unavailable_or_missing_scope_does_not_expose_preserved_old_prices(self):
        self.assertEqual(build_match_comparison_groups(self.match, "live"), [])
        self.snapshot.available = False
        self.snapshot.save(update_fields=["available"])
        self.assertEqual(build_match_comparison_groups(self.match), [])


@override_settings(NEUROKEFF_PREMATCH_ODDS_STALE_SECONDS=3600, NEUROKEFF_LIVE_ODDS_STALE_SECONDS=60)
class BestOddsTests(ComparisonGroupingTests):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.match.sync_scope = "prematch"
        self.match.starts_at = self.now + timedelta(hours=2)
        self.match.save(update_fields=["sync_scope", "starts_at"])
        self.snapshot.provider_updated_at = self.now - timedelta(seconds=10)
        self.snapshot.save(update_fields=["provider_updated_at"])

    def compare(self):
        return build_match_odds_comparison(self.match, now=self.now)

    def assert_unranked(self, status):
        result = self.compare()
        self.assertEqual(result["status"], status)
        self.assertTrue(result["groups"])
        for group in result["groups"]:
            self.assertIsNone(group["best_coefficient"])
            self.assertEqual(group["best_bookmakers"], [])
            self.assertFalse(any(o["is_best"] for o in group["offers"]))

    def test_selects_maximum_with_decimal_precision(self):
        first, second = self.snapshot.bookmakers.all()
        first.markets = [market(price="2.005")]
        second.markets = [market(price="2.0049")]
        first.save(update_fields=["markets"])
        second.save(update_fields=["markets"])
        group = self.compare()["groups"][0]
        self.assertEqual(group["best_coefficient"], "2.005")
        self.assertEqual(group["best_bookmakers"], [{"bookmaker_key": first.bookmaker_key, "bookmaker": first.name}])
        self.assertTrue(group["has_comparison"])

    def test_equal_maximum_marks_all_winners(self):
        self.snapshot.bookmakers.update(markets=[market(price="2.0500")])
        group = self.compare()["groups"][0]
        self.assertEqual(group["best_coefficient"], "2.05")
        self.assertEqual(len(group["best_bookmakers"]), 2)
        self.assertTrue(all(o["is_best"] for o in group["offers"]))

    def test_single_bookmaker_is_not_best(self):
        self.snapshot.bookmakers.filter(bookmaker_key="1").delete()
        group = self.compare()["groups"][0]
        self.assertEqual(group["status"], "single_bookmaker")
        self.assertIsNone(group["best_coefficient"])
        self.assertFalse(group["has_comparison"])

    def test_duplicate_named_bookmaker_does_not_create_comparison(self):
        self.snapshot.bookmakers.update(name="One BK")
        self.assertEqual(self.compare()["groups"], [])
        self.snapshot.bookmakers.update(markets=[market(price="2.05")])
        group = self.compare()["groups"][0]
        self.assertEqual(group["bookmaker_count"], 1)
        self.assertIsNone(group["best_coefficient"])

    def test_old_provider_line_stays_stale_after_new_fetch(self):
        self.snapshot.fetched_at = self.now
        self.snapshot.provider_updated_at = self.now - timedelta(seconds=3601)
        self.snapshot.save(update_fields=["fetched_at", "provider_updated_at"])
        self.assert_unranked("stale")

    def test_old_fetch_is_stale_even_with_recent_provider_date(self):
        self.snapshot.fetched_at = self.now - timedelta(seconds=3601)
        self.snapshot.save(update_fields=["fetched_at"])
        self.assert_unranked("stale")

    def test_missing_provider_time_is_not_assumed_fresh(self):
        self.snapshot.provider_updated_at = None
        self.snapshot.save(update_fields=["provider_updated_at"])
        self.assert_unranked("unknown_freshness")

    def test_future_dates_are_not_eligible(self):
        for field in ("fetched_at", "provider_updated_at"):
            previous = getattr(self.snapshot, field)
            setattr(self.snapshot, field, self.now + timedelta(minutes=1))
            self.snapshot.save(update_fields=[field])
            self.assert_unranked("invalid_timestamp")
            setattr(self.snapshot, field, previous)
            self.snapshot.save(update_fields=[field])

    def test_freshness_boundary_is_inclusive(self):
        self.snapshot.provider_updated_at = self.now - timedelta(seconds=3600)
        self.snapshot.save(update_fields=["provider_updated_at"])
        self.assertEqual(self.compare()["status"], "ready")

    def test_finished_match_ranks_archive_but_started_prematch_is_not_current(self):
        self.match.sync_scope = "finished"
        result = build_match_odds_comparison(self.match, now=self.now)
        self.assertEqual(result["status"], "finished")
        self.assertTrue(any(group["best_coefficient"] for group in result["groups"]))
        self.match.sync_scope = "prematch"
        self.match.starts_at = self.now - timedelta(seconds=1)
        self.assert_unranked("match_started")

    def test_prematch_is_not_a_fallback_for_missing_live_line(self):
        self.match.sync_scope = "live"
        result = self.compare()
        self.assertEqual(result["scope"], "live")
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["groups"], [])
        result = build_match_odds_comparison(self.match, scope="prematch", now=self.now)
        self.assertEqual(result["status"], "scope_mismatch")
        self.assertIsNone(result["groups"][0]["best_coefficient"])

    def test_live_has_shorter_freshness_window(self):
        self.match.sync_scope = "live"
        self.snapshot.scope = "live"
        self.snapshot.provider_updated_at = self.now - timedelta(seconds=61)
        self.snapshot.save(update_fields=["scope", "provider_updated_at"])
        self.assert_unranked("stale")
        self.snapshot.provider_updated_at = self.now - timedelta(seconds=60)
        self.snapshot.save(update_fields=["provider_updated_at"])
        self.assertEqual(self.compare()["status"], "ready")

    def test_suspended_highest_offer_is_excluded(self):
        top = self.snapshot.bookmakers.get(bookmaker_key="1")
        top.markets[0]["suspended"] = True
        top.save(update_fields=["markets"])
        group = self.compare()["groups"][0]
        self.assertEqual(group["bookmaker_count"], 1)
        self.assertIsNone(group["best_coefficient"])
        self.assertEqual(group["offers"][0]["coefficient"], "1.91")

    def test_empty_and_unavailable_are_distinct(self):
        self.snapshot.bookmakers.all().delete()
        self.assertEqual(self.compare()["status"], "empty")
        self.snapshot.available = False
        self.snapshot.save(update_fields=["available"])
        result = self.compare()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["groups"], [])

    def test_invalid_scope_is_rejected(self):
        with self.assertRaises(ValueError):
            build_match_odds_comparison(self.match, scope="finished", now=self.now)
