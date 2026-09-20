import tempfile
from decimal import Decimal
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from cabinet.models import AnalystFollow, User

from achievements.management.commands.seed_achievements import (
    EXPERT_ACHIEVEMENT_DEFINITIONS,
    REFERRAL_ACHIEVEMENT_DEFINITIONS,
    USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS,
)
from achievements.models import Achievement, AchievementCategory, UserAchievement
from achievements.services import (
    award_achievement,
    build_achievement_badges,
    build_achievement_overview,
    get_analyst_achievement_definitions,
    sync_user_achievements,
)
from notifications.models import Notification, NotificationPreference


ALL_SEEDED_DEFINITIONS = (
    EXPERT_ACHIEVEMENT_DEFINITIONS
    + REFERRAL_ACHIEVEMENT_DEFINITIONS
    + USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS
)


class SeedAchievementsTests(TestCase):
    def run_seed(self):
        call_command("seed_achievements", stdout=StringIO())

    def test_seed_achievements_creates_legacy_definitions(self):
        self.run_seed()

        self.assertEqual(
            Achievement.objects.count(),
            len(ALL_SEEDED_DEFINITIONS),
        )
        self.assertEqual(
            AchievementCategory.objects.count(),
            len({item["category"] for item in ALL_SEEDED_DEFINITIONS}),
        )

        first_pick = Achievement.objects.select_related("category").get(
            key="first-pick"
        )
        self.assertEqual(first_pick.title, "Первый прогноз")
        self.assertEqual(first_pick.description, "Опубликуйте первый прогноз")
        self.assertEqual(
            first_pick.fallback_static_icon,
            "front/img/badges/first-pick.svg",
        )
        self.assertEqual(first_pick.metric, Achievement.Metric.PREDICTIONS)
        self.assertEqual(first_pick.target_value, Decimal("1.00"))
        self.assertEqual(first_pick.category.title, "Прогнозы")
        self.assertEqual(first_pick.audience, Achievement.Audience.ANALYST)

        likes = Achievement.objects.get(key="likes-5")
        self.assertEqual(likes.audience, Achievement.Audience.ALL)

    def test_seed_achievements_is_idempotent(self):
        self.run_seed()
        first_ids = dict(Achievement.objects.values_list("key", "id"))
        category_ids = dict(
            AchievementCategory.objects.values_list("slug", "id")
        )

        self.run_seed()

        self.assertEqual(
            dict(Achievement.objects.values_list("key", "id")),
            first_ids,
        )
        self.assertEqual(
            dict(AchievementCategory.objects.values_list("slug", "id")),
            category_ids,
        )
        self.assertEqual(
            Achievement.objects.count(),
            len(ALL_SEEDED_DEFINITIONS),
        )


class AchievementServiceTests(TestCase):
    def setUp(self):
        self.category = AchievementCategory.objects.create(
            title="Тестовая категория",
            slug="test-category",
        )
        self.reader = User.objects.create_user(
            username="achievement-reader",
            email="achievement-reader@example.com",
            password="test-password",
        )
        self.analyst = User.objects.create_user(
            username="achievement-analyst",
            email="achievement-analyst@example.com",
            password="test-password",
            role=User.Role.ANALYST,
        )

    def create_achievement(self, **overrides):
        values = {
            "category": self.category,
            "key": "test-achievement",
            "title": "Тестовое достижение",
            "description": "Описание тестового достижения",
            "audience": Achievement.Audience.ANALYST,
            "metric": Achievement.Metric.FOLLOWERS,
            "target_value": Decimal("1"),
        }
        values.update(overrides)
        return Achievement.objects.create(**values)

    def test_user_receives_achievement_when_target_is_reached(self):
        achievement = self.create_achievement()
        AnalystFollow.objects.create(
            follower=self.reader,
            analyst=self.analyst,
        )

        created = sync_user_achievements(
            self.analyst,
            notify=False,
        )

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].achievement_id, achievement.id)
        user_achievement = UserAchievement.objects.get(
            user=self.analyst,
            achievement=achievement,
        )
        self.assertEqual(user_achievement.progress_percent, 100)
        self.assertEqual(user_achievement.progress_value, Decimal("1.00"))

    def test_inactive_achievement_is_hidden_and_not_awarded(self):
        achievement = self.create_achievement(is_active=False)
        AnalystFollow.objects.create(
            follower=self.reader,
            analyst=self.analyst,
        )

        overview = build_achievement_overview(
            self.analyst,
            followers_count=1,
            is_verified=False,
        )
        created = sync_user_achievements(
            self.analyst,
            notify=False,
        )

        self.assertEqual(overview["items"], [])
        self.assertEqual(created, [])
        self.assertFalse(
            UserAchievement.objects.filter(
                user=self.analyst,
                achievement=achievement,
            ).exists()
        )

    def test_build_achievement_overview_keeps_compatible_format(self):
        self.create_achievement(target_value=Decimal("2"))
        AnalystFollow.objects.create(
            follower=self.reader,
            analyst=self.analyst,
        )

        overview = build_achievement_overview(
            self.analyst,
            followers_count=1,
            is_verified=False,
        )

        self.assertEqual(
            set(overview),
            {
                "items",
                "unlocked_count",
                "total_count",
                "completion_percent",
                "next_achievement",
                "metrics",
            },
        )
        self.assertEqual(len(overview["items"]), 1)
        item = overview["items"][0]
        self.assertTrue(
            {
                "key",
                "label",
                "title",
                "description",
                "icon",
                "icon_url",
                "category",
                "unlocked",
                "progress",
                "current_label",
                "target_label",
            }.issubset(item)
        )
        self.assertEqual(item["key"], "test-achievement")
        self.assertEqual(item["label"], "Тестовое достижение")
        self.assertEqual(item["title"], item["label"])
        self.assertFalse(item["unlocked"])
        self.assertEqual(item["progress"], 50)
        self.assertEqual(overview["next_achievement"]["key"], item["key"])

    def test_uploaded_icon_url_has_priority_over_static_fallback(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.create_achievement(
                    audience=Achievement.Audience.ALL,
                    metric=Achievement.Metric.LIKES_GIVEN,
                    target_value=Decimal("1"),
                    icon=SimpleUploadedFile(
                        "badge.svg",
                        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
                        content_type="image/svg+xml",
                    ),
                    fallback_static_icon="front/img/badges/fallback.svg",
                )

                overview = build_achievement_overview(self.reader)
                item = overview["items"][0]

        self.assertTrue(
            item["icon_url"].endswith(
                "/achievements/icons/badge.svg"
            )
        )
        self.assertEqual(
            item["icon"],
            "front/img/badges/fallback.svg",
        )

    def test_manual_award_is_idempotent(self):
        achievement = self.create_achievement(
            audience=Achievement.Audience.ALL,
            metric=Achievement.Metric.LIKES_GIVEN,
        )

        first = award_achievement(
            self.reader,
            achievement,
            source=UserAchievement.Source.MANUAL,
        )
        second = award_achievement(
            self.reader,
            achievement,
            source=UserAchievement.Source.MANUAL,
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            UserAchievement.objects.filter(
                user=self.reader,
                achievement=achievement,
            ).count(),
            1,
        )
        self.assertEqual(first.source, UserAchievement.Source.MANUAL)

    def test_manual_award_is_visible_in_badges(self):
        achievement = self.create_achievement(target_value=Decimal("10"))
        award_achievement(
            self.analyst,
            achievement,
            source=UserAchievement.Source.MANUAL,
        )

        badges = build_achievement_badges(
            predictions_count=0,
            wins_count=0,
            overall_roi=0,
            followers_count=0,
            best_win_streak=0,
            is_verified=False,
            user=self.analyst,
        )

        self.assertEqual(
            [item["key"] for item in badges],
            ["test-achievement"],
        )

    def test_preloaded_badge_definitions_do_not_query_database(self):
        self.create_achievement(target_value=Decimal("1"))
        definitions = list(get_analyst_achievement_definitions())

        with self.assertNumQueries(0):
            badges = build_achievement_badges(
                predictions_count=0,
                wins_count=0,
                overall_roi=0,
                followers_count=1,
                best_win_streak=0,
                is_verified=False,
                achievements=definitions,
                awarded_ids=(),
            )

        self.assertEqual(len(badges), 1)

    def test_achievement_sync_does_not_duplicate_notification(self):
        achievement = self.create_achievement(
            audience=Achievement.Audience.ALL,
            metric=Achievement.Metric.LIKES_GIVEN,
            target_value=Decimal("0"),
        )
        preferences, _ = NotificationPreference.objects.get_or_create(
            user=self.reader
        )
        preferences.achievement = True
        preferences.save(update_fields=["achievement", "updated_at"])

        with self.captureOnCommitCallbacks(execute=True):
            first = sync_user_achievements(self.reader, notify=True)
        with self.captureOnCommitCallbacks(execute=True):
            second = sync_user_achievements(self.reader, notify=True)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(
            Notification.objects.filter(
                event_key=(
                    f"achievement:{self.reader.pk}:{achievement.key}"
                )
            ).count(),
            1,
        )
