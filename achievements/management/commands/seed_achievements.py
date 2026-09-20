from decimal import Decimal

from django.core.management.base import BaseCommand

from achievements.models import Achievement, AchievementCategory


EXPERT_ACHIEVEMENT_DEFINITIONS = (
    {"key": "first-pick", "label": "Первый прогноз", "description": "Опубликуйте первый прогноз", "icon": "front/img/badges/first-pick.svg", "metric": "predictions", "target": 1, "category": "Прогнозы"},
    {"key": "predictions-5", "label": "5 прогнозов", "description": "Опубликуйте минимум 5 прогнозов", "icon": "front/img/badges/predictions-5.svg", "metric": "predictions", "target": 5, "category": "Прогнозы"},
    {"key": "predictions-25", "label": "25 прогнозов", "description": "Опубликуйте минимум 25 прогнозов", "icon": "front/img/badges/predictions-25.svg", "metric": "predictions", "target": 25, "category": "Прогнозы"},
    {"key": "predictions-50", "label": "50 прогнозов", "description": "Опубликуйте минимум 50 прогнозов", "icon": "front/img/badges/predictions-50.svg", "metric": "predictions", "target": 50, "category": "Прогнозы"},
    {"key": "wins-3", "label": "3 победы", "description": "Выиграйте минимум 3 прогноза", "icon": "front/img/badges/wins-3.svg", "metric": "wins", "target": 3, "category": "Победы"},
    {"key": "wins-10", "label": "10 побед", "description": "Выиграйте минимум 10 прогнозов", "icon": "front/img/badges/wins-10.svg", "metric": "wins", "target": 10, "category": "Победы"},
    {"key": "wins-25", "label": "25 побед", "description": "Выиграйте минимум 25 прогнозов", "icon": "front/img/badges/wins-25.svg", "metric": "wins", "target": 25, "category": "Победы"},
    {"key": "wins-50", "label": "50 побед", "description": "Выиграйте минимум 50 прогнозов", "icon": "front/img/badges/wins-50.svg", "metric": "wins", "target": 50, "category": "Победы"},
    {"key": "roi-5", "label": "ROI +5%", "description": "Достигните текущего ROI не ниже +5%", "icon": "front/img/badges/roi-5.svg", "metric": "roi", "target": 5, "category": "ROI"},
    {"key": "roi-10", "label": "ROI +10%", "description": "Достигните текущего ROI не ниже +10%", "icon": "front/img/badges/roi-10.svg", "metric": "roi", "target": 10, "category": "ROI"},
    {"key": "roi-20", "label": "ROI +20%", "description": "Достигните текущего ROI не ниже +20%", "icon": "front/img/badges/roi-20.svg", "metric": "roi", "target": 20, "category": "ROI"},
    {"key": "roi-50", "label": "ROI +50%", "description": "Достигните текущего ROI не ниже +50%", "icon": "front/img/badges/roi-50.svg", "metric": "roi", "target": 50, "category": "ROI"},
    {"key": "followers-10", "label": "10 подписчиков", "description": "Соберите минимум 10 подписчиков", "icon": "front/img/badges/followers-10.svg", "metric": "followers", "target": 10, "category": "Аудитория"},
    {"key": "followers-50", "label": "50 подписчиков", "description": "Соберите минимум 50 подписчиков", "icon": "front/img/badges/followers-50.svg", "metric": "followers", "target": 50, "category": "Аудитория"},
    {"key": "followers-100", "label": "100 подписчиков", "description": "Соберите минимум 100 подписчиков", "icon": "front/img/badges/followers-100.svg", "metric": "followers", "target": 100, "category": "Аудитория"},
    {"key": "followers-250", "label": "250 подписчиков", "description": "Соберите минимум 250 подписчиков", "icon": "front/img/badges/followers-250.svg", "metric": "followers", "target": 250, "category": "Аудитория"},
    {"key": "streak-3", "label": "3 победы подряд", "description": "Соберите серию минимум из 3 побед подряд", "icon": "front/img/badges/streak-3.svg", "metric": "streak", "target": 3, "category": "Серии"},
    {"key": "streak-5", "label": "5 побед подряд", "description": "Соберите серию минимум из 5 побед подряд", "icon": "front/img/badges/streak-5.svg", "metric": "streak", "target": 5, "category": "Серии"},
    {"key": "streak-10", "label": "10 побед подряд", "description": "Соберите серию минимум из 10 побед подряд", "icon": "front/img/badges/streak-10.svg", "metric": "streak", "target": 10, "category": "Серии"},
    {"key": "verified", "label": "Проверенный эксперт", "description": "Получите подтверждение профиля администрацией", "icon": "front/img/badges/verified.svg", "metric": "verified", "target": 1, "category": "Статус"},
)

REFERRAL_ACHIEVEMENT_DEFINITIONS = (
    {"key": "referrals-5", "label": "Первые 5 рефералов", "description": "Приведите 5 пользователей, которые подпишутся на вас по реферальной ссылке", "icon": "front/img/badges/referrals.svg", "metric": "referrals", "target": 5, "category": "Рефералы"},
    {"key": "referrals-10", "label": "10 рефералов", "description": "Получите 10 подписок после перехода по вашей реферальной ссылке", "icon": "front/img/badges/referrals.svg", "metric": "referrals", "target": 10, "category": "Рефералы"},
    {"key": "referrals-25", "label": "25 рефералов", "description": "Получите 25 подписок после перехода по вашей реферальной ссылке", "icon": "front/img/badges/referrals.svg", "metric": "referrals", "target": 25, "category": "Рефералы"},
    {"key": "referrals-50", "label": "50 рефералов", "description": "Получите 50 подписок после перехода по вашей реферальной ссылке", "icon": "front/img/badges/referrals.svg", "metric": "referrals", "target": 50, "category": "Рефералы"},
)

USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS = (
    {"key": "likes-5", "label": "5 лайков", "description": "Поставьте лайк 5 прогнозам", "icon": "front/img/badges/likes.svg", "metric": "likes_given", "target": 5, "category": "Активность"},
    {"key": "likes-10", "label": "10 лайков", "description": "Поставьте лайк 10 прогнозам", "icon": "front/img/badges/likes.svg", "metric": "likes_given", "target": 10, "category": "Активность"},
    {"key": "likes-25", "label": "25 лайков", "description": "Поставьте лайк 25 прогнозам", "icon": "front/img/badges/likes.svg", "metric": "likes_given", "target": 25, "category": "Активность"},
    {"key": "likes-50", "label": "50 лайков", "description": "Поставьте лайк 50 прогнозам", "icon": "front/img/badges/likes.svg", "metric": "likes_given", "target": 50, "category": "Активность"},
    {"key": "favorites-5", "label": "5 сохранений", "description": "Сохраните 5 прогнозов в избранное", "icon": "front/img/badges/favorites.svg", "metric": "favorites_saved", "target": 5, "category": "Активность"},
    {"key": "favorites-10", "label": "10 сохранений", "description": "Сохраните 10 прогнозов в избранное", "icon": "front/img/badges/favorites.svg", "metric": "favorites_saved", "target": 10, "category": "Активность"},
    {"key": "favorites-25", "label": "25 сохранений", "description": "Сохраните 25 прогнозов в избранное", "icon": "front/img/badges/favorites.svg", "metric": "favorites_saved", "target": 25, "category": "Активность"},
    {"key": "favorites-50", "label": "50 сохранений", "description": "Сохраните 50 прогнозов в избранное", "icon": "front/img/badges/favorites.svg", "metric": "favorites_saved", "target": 50, "category": "Активность"},
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
