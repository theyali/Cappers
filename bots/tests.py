from decimal import Decimal
from tempfile import TemporaryDirectory
from datetime import timedelta
from io import BytesIO, StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from PIL import Image

from bots.models import (
    BotAccount,
    BotExpertStrategy,
    BotOnlineSession,
    BotPlannedAction,
    BotRuntimeControl,
)
from bots.services import (
    _available_picks,
    _candidate_score,
    _express_probability,
    _like_prediction,
    _pick_is_reasonable,
    _target_coefficient,
    cleanup_bot_runtime_data,
    get_bot_runtime_status,
    preview_bot_predictions,
    preview_bot_tournament_activity,
    reset_stale_bot_planned_actions,
    run_bot_activity,
    run_bot_planned_actions,
    run_bot_presence_activity,
    run_bot_predictions,
    run_bot_tournament_activity,
    set_bot_runtime_mode,
)
from cabinet.models import PresetAvatar, User
from cabinet.presence import UserPresence
from front.models import PredictionLike
from game.models import Country, Match, MatchOdds, Prediction, PredictionCoupon, Sport
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class BotProfileEditingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username="bot-admin", is_staff=True)
        cls.real_user = User.objects.create_user(username="ordinary-user")
        cls.expert = User.objects.create_user(username="expert-bot", role=User.Role.ANALYST)
        cls.bot = BotAccount.objects.create(user=cls.expert, kind=BotAccount.Kind.EXPERT)
        cls.country = Country.objects.create(code="AZ", name="Azerbaijan", name_ru="Азербайджан")

    def setUp(self):
        self.client.force_login(self.staff)
        self.url = reverse("bots:edit_account", args=[self.bot.pk])

    def payload(self, **changes):
        return {
            "account-username": self.expert.username, "account-first_name": "Иван",
            "account-last_name": "Петров", "account-gender": User.Gender.MALE,
            "account-country": str(self.country.pk), "account-email": "bot@example.test",
            "account-telegram_username": "expert_telegram",
            "profile-display_name": "Публичное имя", "profile-bio": "Описание бота",
            "profile-specialization": "Футбольная аналитика", "profile-favorite_sports": "Футбол",
            "profile-favorite_leagues": "АПЛ", "profile-telegram_channel": "@channel",
            "profile-telegram_account": "@account", "profile-instagram": "@instagram",
            "profile-threads": "@threads", "profile-youtube": "https://youtube.com/@channel",
            "profile-tiktok": "@tiktok", "profile-facebook": "https://facebook.com/bot",
            "profile-x": "@expert", "profile-is_public": "on", "profile-is_verified": "on",
            "profile-is_recommended": "on", "bot-is_active": "on", "bot-persona": "Футболист",
            **changes,
        }

    def test_full_editor_is_private_and_only_accepts_bots(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.real_user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.payload()).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("bots:edit_account", args=[999999])).status_code, 404)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="account-country"')
        self.assertContains(response, 'name="profile-youtube"')
        self.assertContains(response, 'name="account-remove_avatar"')

    def test_saves_all_public_fields_country_and_bot_settings(self):
        response = self.client.post(self.url, self.payload())
        self.assertRedirects(response, reverse("bots:manage_accounts"))
        self.expert.refresh_from_db()
        profile = self.expert.analyst_profile
        self.bot.refresh_from_db()
        self.assertEqual(self.expert.country_id, self.country.pk)
        self.assertEqual(self.expert.gender, User.Gender.MALE)
        self.assertEqual(self.expert.telegram_username, "expert_telegram")
        self.assertEqual(profile.display_name, "Публичное имя")
        self.assertEqual(profile.bio, "Описание бота")
        self.assertEqual(len(profile.social_links), 8)
        self.assertEqual(profile.favorite_leagues, "АПЛ")
        self.assertTrue(profile.is_verified)
        self.assertTrue(profile.is_recommended)
        self.assertEqual(self.bot.persona, "Футболист")

    def test_can_clear_all_social_links_description_country_and_avatar(self):
        self.client.post(self.url, self.payload())
        self.expert.avatar = "users/old-avatar.png"
        self.expert.save(update_fields=["avatar"])
        data = self.payload(**{
            "account-country": "", "account-remove_avatar": "on", "profile-bio": "",
            **{f"profile-{name}": "" for name in (
                "telegram_channel", "telegram_account", "instagram", "threads", "youtube", "tiktok", "facebook", "x",
            )},
        })
        data.pop("bot-is_active")
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        self.expert.refresh_from_db()
        self.bot.refresh_from_db()
        self.assertIsNone(self.expert.country_id)
        self.assertFalse(self.expert.avatar)
        self.assertEqual(self.expert.analyst_profile.bio, "")
        self.assertEqual(self.expert.analyst_profile.social_links, [])
        self.assertFalse(self.bot.is_active)

    def test_invalid_profile_keeps_every_model_unchanged_and_preserves_input(self):
        response = self.client.post(self.url, self.payload(**{"profile-bio": "x" * 2001}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["profile_form"].errors)
        self.assertContains(response, "bot@example.test")
        self.expert.refresh_from_db()
        self.bot.refresh_from_db()
        self.assertEqual(self.expert.first_name, "")
        self.assertEqual(self.expert.analyst_profile.bio, "")
        self.assertEqual(self.bot.persona, "")

    def test_rejects_duplicate_username_and_email_without_partial_saves(self):
        User.objects.filter(pk=self.real_user.pk).update(email="used@example.test")
        for changes in ({"account-username": self.real_user.username.upper()}, {"account-email": "USED@example.test"}):
            response = self.client.post(self.url, self.payload(**changes))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["user_form"].errors)
        self.expert.refresh_from_db()
        self.assertEqual(self.expert.username, "expert-bot")
        self.assertEqual(self.expert.analyst_profile.bio, "")

    def test_email_change_resets_verification_and_security_flags_are_not_editable(self):
        User.objects.filter(pk=self.expert.pk).update(email="old@example.test", email_verified=True)
        self.client.post(self.url, self.payload(**{"account-is_staff": "on", "account-is_superuser": "on"}))
        self.expert.refresh_from_db()
        self.assertEqual(self.expert.email, "bot@example.test")
        self.assertFalse(self.expert.email_verified)
        self.assertFalse(self.expert.is_staff)
        self.assertFalse(self.expert.is_superuser)

    def test_reader_profile_can_be_stored_without_changing_role(self):
        reader = User.objects.create_user(username="reader-bot")
        bot = BotAccount.objects.create(user=reader, kind=BotAccount.Kind.READER)
        response = self.client.post(reverse("bots:edit_account", args=[bot.pk]), self.payload(**{"account-username": reader.username}))
        self.assertEqual(response.status_code, 302)
        reader.refresh_from_db()
        self.assertEqual(reader.role, User.Role.READER)
        self.assertEqual(reader.analyst_profile.bio, "Описание бота")

    def test_quick_edit_preserves_custom_public_name_and_profile_fields(self):
        profile = self.expert.analyst_profile
        profile.display_name = "Своё имя"
        profile.bio = "Сохранить описание"
        profile.youtube = "@channel"
        profile.save()
        prefix = f"bot-{self.bot.pk}"
        response = self.client.post(reverse("bots:manage_accounts"), {
            "bot_id": self.bot.pk, f"{prefix}-username": self.expert.username,
            f"{prefix}-first_name": "Новое имя", f"{prefix}-last_name": "",
        })
        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.display_name, "Своё имя")
        self.assertEqual(profile.bio, "Сохранить описание")
        self.assertEqual(profile.youtube, "@channel")

    def test_avatar_uploads_preserve_profile_and_country(self):
        with TemporaryDirectory() as media_dir, override_settings(MEDIA_ROOT=media_dir):
            self.client.post(self.url, self.payload())
            for target, field_name, data in (
                (self.url, "account-avatar", self.payload()),
                (reverse("bots:upload_avatar", args=[self.bot.pk]), "avatar", {}),
            ):
                content = BytesIO()
                Image.new("RGB", (16, 16)).save(content, format="PNG")
                response = self.client.post(target, {
                    **data, field_name: SimpleUploadedFile("avatar.png", content.getvalue(), content_type="image/png"),
                })
                self.assertIn(response.status_code, (200, 302))
                self.expert.refresh_from_db()
                self.assertTrue(self.expert.avatar)
                self.assertEqual(self.expert.country_id, self.country.pk)
                self.assertEqual(self.expert.analyst_profile.bio, "Описание бота")
                self.assertEqual(self.expert.analyst_profile.display_name, "Публичное имя")


class BotPickSelectionTests(SimpleTestCase):
    def test_available_picks_skip_direct_zero_handicap(self):
        match = SimpleNamespace(
            home_team_name="Home U21",
            away_team_name="Away",
            odds=SimpleNamespace(
                home_win_bet=1.90,
                x_bet=3.30,
                away_win_bet=4.20,
                goals_over_2_5=1.85,
                goals_under_2_5=1.95,
                btts_yes=1.80,
                btts_no=2.00,
                d_1x=1.22,
                d_2x=1.74,
                fora_1_0=1.66,
                fora_2_0=2.24,
                totals_all={},
                double_chance_all={},
                btts_all={},
                handicaps_all={"Home U21 0": 1.66, "Home U21 -1.5": 2.35, "Away +1.5": 1.62},
            ),
        )

        selections = [pick.selection for pick in _available_picks(match)]

        self.assertNotIn("Home U21 фора 0", selections)
        self.assertNotIn("Away фора 0", selections)
        self.assertIn("Home U21 фора -1.5", selections)
        self.assertIn("Away фора +1.5", selections)

    def test_unrealistic_high_coefficient_is_rejected(self):
        strategy = SimpleNamespace(risk_profile=BotExpertStrategy.RiskProfile.BALANCED)
        match = SimpleNamespace(sport_code="football")
        pick = SimpleNamespace(market="total", selection="ТБ 6.5", coefficient=Decimal("21.00"))

        self.assertFalse(_pick_is_reasonable(match, pick, strategy))

    def test_safe_candidate_score_prefers_profile_coefficient_target(self):
        now = timezone.now()
        strategy = SimpleNamespace(
            risk_profile=BotExpertStrategy.RiskProfile.SAFE,
            bot_id=0,
        )
        match = SimpleNamespace(
            starts_at=now + timedelta(hours=4),
            sport_code="football",
            league_id=1,
            league_name="Premier League",
            league_name_en="Premier League",
        )
        target_pick = SimpleNamespace(market="winner", selection="Home", coefficient=Decimal("1.62"))
        high_pick = SimpleNamespace(market="winner", selection="Away", coefficient=Decimal("2.20"))

        self.assertGreater(
            _candidate_score(match, target_pick, strategy, now),
            _candidate_score(match, high_pick, strategy, now),
        )

    def test_late_aggressive_tournament_raises_target_coefficient(self):
        now = timezone.now()
        strategy = SimpleNamespace(risk_profile=BotExpertStrategy.RiskProfile.AGGRESSIVE)
        tournament = SimpleNamespace(
            starts_at=now - timedelta(days=3),
            ends_at=now + timedelta(hours=6),
        )

        self.assertEqual(
            _target_coefficient(strategy, tournament=tournament, now=now),
            Decimal("2.80"),
        )


class BotRuntimeTests(TestCase):
    def _analyst_bot(self, username: str) -> BotAccount:
        user = User.objects.create_user(
            username=username,
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        bot = BotAccount.objects.create(
            user=user,
            kind=BotAccount.Kind.EXPERT,
            persona=username,
            is_active=True,
        )
        BotExpertStrategy.objects.create(
            bot=bot,
            daily_predictions_min=1,
            daily_predictions_max=1,
            next_run_at=timezone.now() - timedelta(minutes=1),
        )
        return bot

    def test_run_bot_predictions_creates_unique_picks_without_comment_field(self):
        self._analyst_bot("bot_expert_one")
        self._analyst_bot("bot_expert_two")
        match = Match.objects.create(
            external_id=1001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(
            match=match,
            home_win_bet=1.91,
            x_bet=3.40,
            away_win_bet=4.10,
            goals_over_2_5=1.86,
            goals_under_2_5=1.94,
            btts_yes=1.82,
            btts_no=1.98,
            d_1x=1.28,
            d_2x=1.75,
            handicaps_all={"Home -1.5": 2.30, "Away +1.5": 1.61},
        )

        result = run_bot_predictions(execute_immediately=True)

        self.assertEqual(result["created"], 2)
        picks = set(Prediction.objects.values_list("match_id", "market", "selection"))
        self.assertEqual(len(picks), 2)
        self.assertFalse(any("фора 0" in selection for _, _, selection in picks))

    def test_run_bot_predictions_avoids_recent_identical_bot_pick(self):
        bot = self._analyst_bot("bot_expert_three")
        bot.expert_strategy.daily_predictions_max = 2
        bot.expert_strategy.save(update_fields=["daily_predictions_max"])
        match = Match.objects.create(
            external_id=1002,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(match=match, home_win_bet=1.80, away_win_bet=2.05)
        coupon = PredictionCoupon.objects.create(
            author=bot.user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("180.00"),
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="Home",
            coefficient=Decimal("1.80"),
            stake=Decimal("100.00"),
        )

        result = run_bot_predictions(execute_immediately=True)

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skip_reasons"], {"no_reasonable_pick": 1})

    def test_like_prediction_uses_coupon_id(self):
        reader = User.objects.create_user(username="reader_bot", password="safe-test-password")
        bot = BotAccount.objects.create(
            user=reader,
            kind=BotAccount.Kind.READER,
            persona="reader",
            is_active=True,
        )
        analyst = User.objects.create_user(
            username="human_analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        coupon = PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("180.00"),
            published_at=timezone.now(),
        )

        self.assertTrue(_like_prediction(bot))
        self.assertTrue(PredictionLike.objects.filter(prediction=coupon, user=reader).exists())
        self.assertEqual(PredictionLike.objects.count(), 1)

    @patch("bots.services._express_probability", return_value=1)
    def test_run_bot_predictions_can_create_express_coupon(self, _probability):
        self._analyst_bot("bot_express")
        now = timezone.now()
        for index in range(3):
            match = Match.objects.create(
                external_id=2000 + index,
                sync_scope=Match.SyncScope.PREMATCH,
                starts_at=now + timedelta(days=1, hours=index),
                raw_data={
                    "teams": {
                        "home": {"name": {"en": f"Home {index}"}},
                        "away": {"name": {"en": f"Away {index}"}},
                    }
                },
            )
            MatchOdds.objects.create(
                match=match,
                home_win_bet=Decimal("1.65"),
                away_win_bet=Decimal("2.10"),
                goals_over_2_5=Decimal("1.75"),
                goals_under_2_5=Decimal("1.95"),
            )

        result = run_bot_predictions(now=now, execute_immediately=True)

        self.assertEqual(result["created"], 1)
        coupon = PredictionCoupon.objects.get(author__username="bot_express")
        self.assertEqual(coupon.coupon_type, PredictionCoupon.CouponType.EXPRESS)
        self.assertGreaterEqual(coupon.predictions.count(), 2)

    @patch("bots.services.random.random", return_value=0)
    def test_tournament_activity_joins_upcoming_ordinary_tournament(self, _random):
        self._analyst_bot("bot_tournament_join")
        tournament = Tournament.objects.create(
            title="Bot Cup Join",
            status=Tournament.Status.PUBLISHED,
            prediction_format=Tournament.PredictionFormat.QUICK,
            starts_at=timezone.now() + timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=2),
        )

        result = run_bot_tournament_activity()

        self.assertEqual(result["joined"], 1)
        self.assertTrue(
            TournamentParticipant.objects.filter(
                tournament=tournament,
                user__username="bot_tournament_join",
                status=TournamentParticipant.Status.ACTIVE,
            ).exists()
        )

    @patch("bots.services.random.random", return_value=0)
    def test_tournament_activity_skips_tournaments_with_written_predictions(self, _random):
        self._analyst_bot("bot_tournament_rich")
        Tournament.objects.create(
            title="Bot Cup Rich",
            status=Tournament.Status.PUBLISHED,
            prediction_format=Tournament.PredictionFormat.RICH,
            starts_at=timezone.now() + timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=2),
        )

        result = run_bot_tournament_activity()

        self.assertEqual(result["reason"], "no_bot_tournaments")
        self.assertFalse(TournamentParticipant.objects.exists())

    def test_tournament_activity_creates_rare_tournament_coupon(self):
        sport = Sport.objects.create(
            external_id=3000,
            code="football",
            name="Football",
            name_ru="Футбол",
        )
        bot = self._analyst_bot("bot_tournament_coupon")
        bot.expert_strategy.daily_predictions_max = 2
        bot.expert_strategy.save(update_fields=["daily_predictions_max"])
        now = timezone.now()
        tournament = Tournament.objects.create(
            title="Bot Cup Coupon",
            status=Tournament.Status.PUBLISHED,
            prediction_format=Tournament.PredictionFormat.QUICK,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=2),
            min_coefficient=Decimal("1.50"),
            coupon_type_rule=Tournament.CouponTypeRule.SINGLE,
        )
        tournament.allowed_sports.add(sport)
        participant = TournamentParticipant.objects.create(
            tournament=tournament,
            user=bot.user,
        )
        TournamentParticipant.objects.filter(pk=participant.pk).update(
            joined_at=now - timedelta(hours=1)
        )
        match = Match.objects.create(
            external_id=3001,
            sport=sport,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(hours=3),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(
            match=match,
            home_win_bet=Decimal("1.70"),
            away_win_bet=Decimal("2.20"),
            goals_over_2_5=Decimal("1.90"),
        )

        result = run_bot_tournament_activity(now=now)

        self.assertEqual(result["created"], 1)
        tournament_coupon = TournamentCoupon.objects.get(tournament=tournament)
        self.assertEqual(tournament_coupon.coupon.author, bot.user)
        self.assertEqual(tournament_coupon.coupon.coupon_type, PredictionCoupon.CouponType.SINGLE)
        self.assertEqual(tournament_coupon.prediction_entries.count(), 1)
        self.assertEqual(tournament_coupon.coupon.tournament, tournament)

    def test_preview_bot_tournament_activity_shows_join_without_side_effects(self):
        self._analyst_bot("bot_tournament_preview_join")
        tournament = Tournament.objects.create(
            title="Bot Cup Preview Join",
            status=Tournament.Status.PUBLISHED,
            prediction_format=Tournament.PredictionFormat.QUICK,
            starts_at=timezone.now() + timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=2),
        )

        result = preview_bot_tournament_activity(limit=3)

        self.assertEqual(result["tournaments"], 1)
        self.assertEqual(len(result["join_previews"]), 1)
        self.assertEqual(result["join_previews"][0]["tournament_id"], tournament.id)
        self.assertFalse(TournamentParticipant.objects.filter(tournament=tournament).exists())

    def test_preview_bot_tournament_activity_shows_coupon_without_side_effects(self):
        sport = Sport.objects.create(
            external_id=3500,
            code="football-preview",
            name="Football Preview",
            name_ru="Футбол Preview",
        )
        bot = self._analyst_bot("bot_tournament_preview_coupon")
        now = timezone.now()
        tournament = Tournament.objects.create(
            title="Bot Cup Preview Coupon",
            status=Tournament.Status.PUBLISHED,
            prediction_format=Tournament.PredictionFormat.QUICK,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=2),
            min_coefficient=Decimal("1.50"),
            coupon_type_rule=Tournament.CouponTypeRule.SINGLE,
        )
        tournament.allowed_sports.add(sport)
        participant = TournamentParticipant.objects.create(
            tournament=tournament,
            user=bot.user,
        )
        TournamentParticipant.objects.filter(pk=participant.pk).update(
            joined_at=now - timedelta(hours=1)
        )
        match = Match.objects.create(
            external_id=3501,
            sport=sport,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(hours=3),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(
            match=match,
            home_win_bet=Decimal("1.70"),
            away_win_bet=Decimal("2.20"),
        )

        result = preview_bot_tournament_activity(now=now, limit=3)

        self.assertEqual(len(result["coupon_previews"]), 1)
        self.assertEqual(result["coupon_previews"][0]["tournament_id"], tournament.id)
        self.assertEqual(result["coupon_previews"][0]["bot"], bot.user.username)
        self.assertEqual(PredictionCoupon.objects.filter(author=bot.user).count(), 0)
        self.assertEqual(TournamentCoupon.objects.filter(tournament=tournament).count(), 0)

    def test_repair_bot_predictions_cancels_bad_published_coupon_only_with_apply(self):
        bot = self._analyst_bot("bot_repair")
        match = Match.objects.create(
            external_id=4001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        coupon = PredictionCoupon.objects.create(
            author=bot.user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("2100.00"),
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="total",
            selection="ТБ 7.5",
            coefficient=Decimal("21.00"),
            stake=Decimal("100.00"),
        )

        call_command("repair_bot_predictions", stdout=StringIO())
        coupon.refresh_from_db()
        self.assertEqual(coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)

        call_command("repair_bot_predictions", "--apply", stdout=StringIO())
        coupon.refresh_from_db()
        self.assertEqual(coupon.published_status, PredictionCoupon.PublishedStatus.CANCELED)

    def test_inspect_bots_outputs_coefficient_buckets_and_queue_issues(self):
        bot = self._analyst_bot("bot_inspect")
        now = timezone.now()
        match = Match.objects.create(
            external_id=4401,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        coupon = PredictionCoupon.objects.create(
            author=bot.user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("210.00"),
            published_at=now,
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="Home",
            coefficient=Decimal("2.10"),
            stake=Decimal("100.00"),
        )
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.FAILED,
            scheduled_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=1),
            error="test failure",
        )

        output = StringIO()
        call_command("inspect_bots", "--hours", "24", stdout=output)
        text = output.getvalue()

        self.assertIn("КФ позиций:", text)
        self.assertIn("'2.00-2.99': 1", text)
        self.assertIn("КФ купонов:", text)
        self.assertIn("Последние проблемы очереди:", text)
        self.assertIn("test failure", text)

    def test_cleanup_bot_runtime_data_removes_old_done_skipped_and_sessions(self):
        bot = self._analyst_bot("bot_cleanup")
        now = timezone.now()
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.DONE,
            scheduled_at=now - timedelta(days=20),
            finished_at=now - timedelta(days=20),
        )
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.SKIPPED,
            scheduled_at=now - timedelta(days=20),
            finished_at=now - timedelta(days=20),
        )
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.FAILED,
            scheduled_at=now - timedelta(days=20),
            finished_at=now - timedelta(days=20),
        )
        BotOnlineSession.objects.create(
            bot=bot,
            starts_at=now - timedelta(days=20, minutes=20),
            ends_at=now - timedelta(days=20),
        )

        result = cleanup_bot_runtime_data(now=now, planned_days=14, sessions_days=14)

        self.assertEqual(result["planned_deleted"], 2)
        self.assertEqual(result["sessions_deleted"], 1)
        self.assertEqual(BotPlannedAction.objects.count(), 1)
        self.assertTrue(
            BotPlannedAction.objects.filter(status=BotPlannedAction.Status.FAILED).exists()
        )
        self.assertEqual(BotOnlineSession.objects.count(), 0)

    def test_reset_stale_bot_planned_actions_returns_running_to_pending(self):
        bot = self._analyst_bot("bot_reset_running")
        now = timezone.now()
        stale = BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.RUNNING,
            scheduled_at=now - timedelta(hours=1),
            started_at=now - timedelta(hours=1),
            error="worker stopped",
        )

        result = reset_stale_bot_planned_actions(now=now, older_minutes=30)

        self.assertEqual(result["reset"], 1)
        stale.refresh_from_db()
        self.assertEqual(stale.status, BotPlannedAction.Status.PENDING)
        self.assertIsNone(stale.started_at)
        self.assertEqual(stale.error, "")

    def test_runtime_mode_can_disable_bot_cycles(self):
        self._analyst_bot("bot_runtime_paused")
        set_bot_runtime_mode(BotRuntimeControl.Mode.PAUSED)

        prediction_result = run_bot_predictions()
        presence_result = run_bot_presence_activity()
        planned_result = run_bot_planned_actions()

        self.assertEqual(prediction_result["reason"], "bot_runtime_disabled")
        self.assertEqual(presence_result["reason"], "bot_runtime_disabled")
        self.assertEqual(planned_result["reason"], "bot_runtime_disabled")
        self.assertFalse(get_bot_runtime_status()["enabled"]["predictions"])

    def test_tournaments_only_runtime_leaves_reader_actions_pending(self):
        bot = self._analyst_bot("bot_runtime_tournaments")
        now = timezone.now()
        reader_action = BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.READER_ACTIVITY,
            scheduled_at=now - timedelta(minutes=1),
        )
        tournament_action = BotPlannedAction.objects.create(
            action=BotPlannedAction.Action.TOURNAMENT_ACTIVITY,
            scheduled_at=now - timedelta(minutes=1),
        )
        set_bot_runtime_mode(BotRuntimeControl.Mode.TOURNAMENTS_ONLY)

        result = run_bot_planned_actions(now=now)

        self.assertEqual(result["due"], 1)
        reader_action.refresh_from_db()
        tournament_action.refresh_from_db()
        self.assertEqual(reader_action.status, BotPlannedAction.Status.PENDING)
        self.assertEqual(tournament_action.status, BotPlannedAction.Status.SKIPPED)

    def test_control_bots_command_sets_runtime_mode(self):
        output = StringIO()

        call_command("control_bots", "--only-presence", stdout=output)

        control = BotRuntimeControl.load()
        self.assertEqual(control.mode, BotRuntimeControl.Mode.PRESENCE_ONLY)
        self.assertIn("presence", output.getvalue())

    def test_run_bot_predictions_plans_action_without_immediate_coupon(self):
        bot = self._analyst_bot("bot_queue_plan")

        result = run_bot_predictions(now=timezone.now())

        self.assertEqual(result["planned"], 1)
        self.assertEqual(PredictionCoupon.objects.filter(author=bot.user).count(), 0)
        action = BotPlannedAction.objects.get(bot=bot)
        self.assertEqual(action.action, BotPlannedAction.Action.PREDICTION)
        self.assertEqual(action.status, BotPlannedAction.Status.PENDING)
        self.assertGreater(action.scheduled_at, timezone.now())

    def test_preview_bot_predictions_has_no_side_effects(self):
        bot = self._analyst_bot("bot_preview")
        now = timezone.now()
        match = Match.objects.create(
            external_id=4501,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(
            match=match,
            home_win_bet=Decimal("1.78"),
            away_win_bet=Decimal("2.05"),
        )

        result = preview_bot_predictions(now=now)

        self.assertEqual(result["strategies"], 1)
        self.assertEqual(len(result["previews"]), 1)
        self.assertEqual(result["previews"][0]["bot"], bot.user.username)
        self.assertEqual(PredictionCoupon.objects.filter(author=bot.user).count(), 0)
        self.assertEqual(BotPlannedAction.objects.filter(bot=bot).count(), 0)

    def test_express_probability_recovers_when_bot_has_no_recent_express(self):
        bot = self._analyst_bot("bot_express_recovery")
        now = timezone.now()
        strategy = bot.expert_strategy

        without_recent = _express_probability(strategy, now=now)
        PredictionCoupon.objects.create(
            author=bot.user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            coupon_type=PredictionCoupon.CouponType.EXPRESS,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("240.00"),
            published_at=now,
        )

        with_recent = _express_probability(strategy, now=now)

        self.assertGreater(without_recent, with_recent)

    def test_run_bot_planned_actions_executes_due_prediction(self):
        bot = self._analyst_bot("bot_queue_execute")
        now = timezone.now()
        match = Match.objects.create(
            external_id=5001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"en": "Home"}},
                    "away": {"name": {"en": "Away"}},
                }
            },
        )
        MatchOdds.objects.create(
            match=match,
            home_win_bet=Decimal("1.75"),
            away_win_bet=Decimal("2.10"),
        )
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.PREDICTION,
            scheduled_at=now - timedelta(minutes=1),
            payload={"strategy_id": bot.expert_strategy.id},
        )

        result = run_bot_planned_actions(now=now)

        self.assertEqual(result["executed"], 1)
        self.assertEqual(PredictionCoupon.objects.filter(author=bot.user).count(), 1)
        action = BotPlannedAction.objects.get(bot=bot)
        self.assertEqual(action.status, BotPlannedAction.Status.DONE)

    def test_run_bot_activity_plans_reader_actions(self):
        user = User.objects.create_user(username="reader_queue", password="safe-test-password")
        bot = BotAccount.objects.create(
            user=user,
            kind=BotAccount.Kind.READER,
            persona="reader",
            is_active=True,
        )
        session = BotOnlineSession.objects.create(
            bot=bot,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(minutes=20),
            target_actions=2,
        )

        result = run_bot_activity(max_actions=5)

        self.assertEqual(result["planned"], 1)
        action = BotPlannedAction.objects.get(bot=bot)
        self.assertEqual(action.action, BotPlannedAction.Action.READER_ACTIVITY)
        self.assertEqual(action.status, BotPlannedAction.Status.PENDING)
        self.assertEqual(action.payload["session_id"], session.id)
        session.refresh_from_db()
        self.assertEqual(session.actions_planned, 1)

    @patch("bots.services.random.uniform", return_value=0.5)
    def test_run_bot_presence_activity_marks_some_bots_online_and_recent(self, _uniform):
        now = timezone.now()
        for index in range(4):
            self._analyst_bot(f"presence_bot_{index}")

        result = run_bot_presence_activity(now=now)

        self.assertEqual(result["online"], 2)
        self.assertEqual(result["recent"], 2)
        self.assertEqual(result["sessions_started"], 2)
        self.assertEqual(result["bots"], 4)
        self.assertEqual(BotOnlineSession.objects.count(), 2)
        last_seen_values = list(UserPresence.objects.values_list("last_seen_at", flat=True))
        self.assertEqual(len(last_seen_values), 4)
        self.assertEqual(sum(1 for value in last_seen_values if now - value <= timedelta(minutes=5)), 2)

    @patch("bots.services._like_prediction", return_value=True)
    @patch("bots.services.random.random", return_value=0)
    def test_bot_online_session_limits_social_actions_to_two(self, _random, _like_prediction):
        now = timezone.now()
        bot = self._analyst_bot("session_action_limit_bot")
        session = BotOnlineSession.objects.create(
            bot=bot,
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(minutes=30),
            target_actions=2,
        )

        first_result = run_bot_activity(max_actions=5)
        BotPlannedAction.objects.filter(bot=bot).update(scheduled_at=now - timedelta(seconds=1))
        first_execute = run_bot_planned_actions(now=now)
        second_result = run_bot_activity(max_actions=5)
        BotPlannedAction.objects.filter(bot=bot, status=BotPlannedAction.Status.PENDING).update(
            scheduled_at=now + timedelta(minutes=1)
        )
        second_execute = run_bot_planned_actions(now=now + timedelta(minutes=2))
        third_result = run_bot_activity(max_actions=5)

        self.assertEqual(first_result["planned"], 1)
        self.assertEqual(first_execute["executed"], 1)
        self.assertEqual(second_result["planned"], 1)
        self.assertEqual(second_execute["executed"], 1)
        self.assertEqual(third_result["planned"], 0)
        session.refresh_from_db()
        self.assertEqual(session.actions_planned, 2)
        self.assertEqual(session.actions_done, 2)

    def test_social_action_without_active_session_is_skipped(self):
        bot = self._analyst_bot("session_required_bot")
        now = timezone.now()
        BotPlannedAction.objects.create(
            bot=bot,
            action=BotPlannedAction.Action.READER_ACTIVITY,
            scheduled_at=now - timedelta(minutes=1),
        )

        result = run_bot_planned_actions(now=now)

        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["reasons"], {"no_active_session": 1})


class BotAvatarCommandTests(TestCase):
    def setUp(self):
        self.media_dir = TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        media_override.enable()
        self.addCleanup(media_override.disable)

    def _preset(self, gender, filename, content):
        return PresetAvatar.objects.create(
            title=filename,
            gender=gender,
            is_active=True,
            image=SimpleUploadedFile(filename, content, content_type="image/png"),
        )

    def _bot(self, username, gender="", *, is_active=True):
        user = User.objects.create_user(
            username=username, password="test-password", gender=gender,
        )
        BotAccount.objects.create(
            user=user, kind=BotAccount.Kind.READER, is_active=is_active,
        )
        return user

    def test_all_bots_use_matching_presets_without_touching_real_users(self):
        self._preset(PresetAvatar.Gender.MALE, "male.png", b"male-image")
        self._preset(PresetAvatar.Gender.FEMALE, "female.png", b"female-image")
        self._preset(PresetAvatar.Gender.ALL, "all.png", b"universal-image")
        male = self._bot("male_bot", User.Gender.MALE)
        female = self._bot("female_bot", User.Gender.FEMALE)
        unknown = self._bot("unknown_bot")
        inactive = self._bot("inactive_bot", is_active=False)
        real = User.objects.create_user(username="real_user", password="test-password")

        output = StringIO()
        call_command("update_bot_avatars", seed=5, stdout=output)

        self.assertIn("Обновлено аватаров: 4", output.getvalue())
        for user, allowed in (
            (male, {b"male-image", b"universal-image"}),
            (female, {b"female-image", b"universal-image"}),
            (unknown, {b"male-image", b"universal-image"}),
            (inactive, {b"male-image", b"universal-image"}),
        ):
            user.refresh_from_db()
            with user.avatar.open("rb") as uploaded:
                self.assertIn(uploaded.read(), allowed)
        real.refresh_from_db()
        self.assertFalse(real.avatar)

    def test_dry_run_does_not_change_existing_avatar(self):
        self._preset(PresetAvatar.Gender.MALE, "male.png", b"male-image")
        user = self._bot("test_bot")
        user.avatar.save("original.png", SimpleUploadedFile("original.png", b"old"), save=True)
        original = user.avatar.name

        output = StringIO()
        call_command("update_bot_avatars", dry_run=True, stdout=output)
        user.refresh_from_db()
        self.assertEqual(user.avatar.name, original)
        self.assertIn("Можно обновить аватаров: 1", output.getvalue())

        call_command("update_bot_avatars", only_missing=True, stdout=StringIO())
        user.refresh_from_db()
        self.assertEqual(user.avatar.name, original)

    def test_replaces_existing_bot_avatar_by_default(self):
        self._preset(PresetAvatar.Gender.MALE, "male.png", b"new-image")
        bot = self._bot("replace_bot")
        bot.avatar.save("old.png", SimpleUploadedFile("old.png", b"old-image"), save=True)
        original = bot.avatar.name

        call_command("update_bot_avatars", stdout=StringIO())
        bot.refresh_from_db()
        self.assertNotEqual(bot.avatar.name, original)
        with bot.avatar.open("rb") as file:
            self.assertEqual(file.read(), b"new-image")

    def test_skips_bots_without_matching_gender(self):
        self._preset(PresetAvatar.Gender.FEMALE, "female.png", b"female-image")
        male = self._bot("male_bot", User.Gender.MALE)
        call_command("update_bot_avatars", stdout=StringIO(), stderr=StringIO())
        male.refresh_from_db()
        self.assertFalse(male.avatar)

    def test_fails_when_no_active_preset_avatars_exist(self):
        self._bot("bot")
        with self.assertRaises(CommandError):
            call_command("update_bot_avatars", stdout=StringIO())
