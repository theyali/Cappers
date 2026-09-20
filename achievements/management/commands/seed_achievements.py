from decimal import Decimal

from django.core.management.base import BaseCommand

from achievements.models import Achievement, AchievementCategory
from cabinet.achievements import (
    EXPERT_ACHIEVEMENT_DEFINITIONS,
    REFERRAL_ACHIEVEMENT_DEFINITIONS,
    USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS,
)


CATEGORY_SLUGS = {
    "Прогнозы": "predictions",
    "Победы": "wins",
    "ROI": "roi",
    "Аудитория": "audience",
    "Серии": "streaks",
    "Статус": "status",
    "Рефералы": "referrals",
    "Активность": "activity",
}


class Command(BaseCommand):
    help = "Создать или обновить базовые достижения."

    def handle(self, *args, **options):
        definition_groups = (
            (EXPERT_ACHIEVEMENT_DEFINITIONS, Achievement.Audience.ANALYST),
            (REFERRAL_ACHIEVEMENT_DEFINITIONS, Achievement.Audience.ANALYST),
            (USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS, Achievement.Audience.ALL),
        )

        categories = {}
        created_categories = 0
        created_achievements = 0
        updated_achievements = 0

        for definitions, audience in definition_groups:
            for definition in definitions:
                category_title = definition["category"]
                category = categories.get(category_title)
                if category is None:
                    slug = CATEGORY_SLUGS[category_title]
                    category, created = AchievementCategory.objects.update_or_create(
                        slug=slug,
                        defaults={
                            "title": category_title,
                            "sort_order": len(categories),
                        },
                    )
                    categories[category_title] = category
                    created_categories += int(created)

                _, created = Achievement.objects.update_or_create(
                    key=definition["key"],
                    defaults={
                        "category": category,
                        "title": definition["label"],
                        "description": definition["description"],
                        "fallback_static_icon": definition["icon"],
                        "audience": audience,
                        "metric": definition["metric"],
                        "target_value": Decimal(str(definition["target"])),
                    },
                )
                if created:
                    created_achievements += 1
                else:
                    updated_achievements += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Готово: "
                f"категорий создано {created_categories}, "
                f"достижений создано {created_achievements}, "
                f"обновлено {updated_achievements}."
            )
        )
