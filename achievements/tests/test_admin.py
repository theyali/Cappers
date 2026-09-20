from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, SimpleTestCase

from achievements.admin import (
    AchievementAdmin,
    AchievementCategoryAdmin,
    UserAchievementAdmin,
)
from achievements.models import Achievement, AchievementCategory, UserAchievement


class AchievementAdminTests(SimpleTestCase):
    def setUp(self):
        self.site = AdminSite()

    def test_category_admin_configuration(self):
        model_admin = AchievementCategoryAdmin(
            AchievementCategory,
            self.site,
        )

        self.assertEqual(
            model_admin.list_display,
            ("title", "slug", "sort_order", "is_active"),
        )
        self.assertEqual(
            model_admin.list_editable,
            ("sort_order", "is_active"),
        )
        self.assertEqual(
            model_admin.search_fields,
            ("title", "slug"),
        )
        self.assertEqual(
            model_admin.prepopulated_fields,
            {"slug": ("title",)},
        )
        self.assertEqual(
            model_admin.ordering,
            ("sort_order", "title"),
        )

    def test_achievement_admin_configuration(self):
        model_admin = AchievementAdmin(Achievement, self.site)

        self.assertEqual(
            model_admin.list_filter,
            ("is_active", "audience", "metric", "category"),
        )
        self.assertEqual(
            model_admin.list_editable,
            ("is_active", "sort_order"),
        )
        self.assertEqual(
            model_admin.autocomplete_fields,
            ("category",),
        )
        self.assertEqual(
            model_admin.readonly_fields,
            ("icon_preview", "created_at", "updated_at"),
        )

    def test_user_achievement_admin_configuration(self):
        model_admin = UserAchievementAdmin(
            UserAchievement,
            self.site,
        )

        self.assertEqual(
            model_admin.list_display,
            (
                "user",
                "achievement",
                "source",
                "progress_percent",
                "unlocked_at",
            ),
        )
        self.assertEqual(
            model_admin.list_filter,
            ("source", "achievement__category", "achievement"),
        )
        self.assertEqual(
            model_admin.autocomplete_fields,
            ("user", "achievement"),
        )
        self.assertEqual(
            model_admin.readonly_fields,
            ("unlocked_at",),
        )
        self.assertIn(
            "resync_selected_users",
            model_admin.actions,
        )

    def test_manual_award_form_defaults_source_to_manual(self):
        request = RequestFactory().get(
            "/admin/achievements/userachievement/add/"
        )
        model_admin = UserAchievementAdmin(
            UserAchievement,
            self.site,
        )

        initial = model_admin.get_changeform_initial_data(request)

        self.assertEqual(
            initial["source"],
            UserAchievement.Source.MANUAL,
        )
