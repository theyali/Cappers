from django.core.management.base import BaseCommand
from django.db import transaction

from cabinet.models import (
    DailyTask,
    ReferralBonusSettings,
    StreakReward,
    XpLevel,
)


DAILY_TASKS = (
    {
        "task_type": DailyTask.TaskType.DAILY_LOGIN,
        "audience": DailyTask.Audience.ALL,
        "title": "Зайти на КапперХаб",
        "description": "Заходите на платформу каждый день.",
        "target_value": 1,
        "reward_xp": 10,
        "reward_coins": 0,
        "reward_spins": 0,
        "order": 10,
    },
    {
        "task_type": DailyTask.TaskType.SPIN_ROULETTE,
        "audience": DailyTask.Audience.ALL,
        "title": "Прокрутить рулетку",
        "description": "Используйте ежедневную попытку в бонусной рулетке.",
        "target_value": 1,
        "reward_xp": 10,
        "reward_coins": 0,
        "reward_spins": 0,
        "order": 20,
    },
    {
        "task_type": DailyTask.TaskType.OPEN_FEED,
        "audience": DailyTask.Audience.ALL,
        "title": "Открыть мою ленту",
        "description": "Посмотрите новые публикации и прогнозы в своей ленте.",
        "target_value": 1,
        "reward_xp": 5,
        "reward_coins": 0,
        "reward_spins": 0,
        "order": 30,
    },
    {
        "task_type": DailyTask.TaskType.VIEW_PREDICTION,
        "audience": DailyTask.Audience.READER,
        "title": "Посмотреть 3 прогноза",
        "description": "Откройте три прогноза за день.",
        "target_value": 3,
        "reward_xp": 10,
        "reward_coins": 0,
        "reward_spins": 0,
        "order": 40,
    },
    {
        "task_type": DailyTask.TaskType.ADD_FAVORITE,
        "audience": DailyTask.Audience.READER,
        "title": "Добавить прогноз в избранное",
        "description": "Сохраните интересный прогноз в избранное.",
        "target_value": 1,
        "reward_xp": 10,
        "reward_coins": 0,
        "reward_spins": 0,
        "order": 50,
    },
    {
        "task_type": DailyTask.TaskType.FOLLOW_CAPPER,
        "audience": DailyTask.Audience.READER,
        "title": "Подписаться на каппера",
        "description": "Подпишитесь на нового каппера.",
        "target_value": 1,
        "reward_xp": 15,
        "reward_coins": 0,
        "reward_spins": 0,
        "order": 60,
    },
    {
        "task_type": DailyTask.TaskType.CREATE_PREDICTION,
        "audience": DailyTask.Audience.CAPPER,
        "title": "Создать прогноз",
        "description": "Создайте новый прогноз или купон.",
        "target_value": 1,
        "reward_xp": 15,
        "reward_coins": 0,
        "reward_spins": 0,
        "order": 40,
    },
    {
        "task_type": DailyTask.TaskType.PUBLISH_PREDICTION,
        "audience": DailyTask.Audience.CAPPER,
        "title": "Опубликовать прогноз",
        "description": "Опубликуйте прогноз для пользователей.",
        "target_value": 1,
        "reward_xp": 20,
        "reward_coins": 0,
        "reward_spins": 0,
        "order": 50,
    },
    {
        "task_type": DailyTask.TaskType.ANSWER_COMMENT,
        "audience": DailyTask.Audience.CAPPER,
        "title": "Ответить на комментарий",
        "description": "Ответьте пользователю под прогнозом.",
        "target_value": 1,
        "reward_xp": 10,
        "reward_coins": 0,
        "reward_spins": 0,
        "order": 60,
    },
    {
        "task_type": DailyTask.TaskType.UPDATE_PROFILE,
        "audience": DailyTask.Audience.CAPPER,
        "title": "Обновить профиль",
        "description": "Обновите данные или аватар профиля.",
        "target_value": 1,
        "reward_xp": 5,
        "reward_coins": 0,
        "reward_spins": 0,
        "order": 70,
    },
)


XP_LEVELS = (
    {"level": 1, "title": "Новичок", "required_xp": 0, "order": 10},
    {"level": 2, "title": "Участник", "required_xp": 100, "order": 20},
    {"level": 3, "title": "Активный", "required_xp": 250, "order": 30},
    {"level": 4, "title": "Опытный", "required_xp": 500, "order": 40},
    {"level": 5, "title": "Эксперт", "required_xp": 900, "order": 50},
)


STREAK_REWARDS = (
    {
        "day_number": 1,
        "title": "Первый день серии",
        "reward_xp": 5,
        "reward_coins": 0,
        "reward_spins": 0,
    },
    {
        "day_number": 3,
        "title": "Три дня подряд",
        "reward_xp": 15,
        "reward_coins": 0,
        "reward_spins": 0,
    },
    {
        "day_number": 7,
        "title": "Неделя активности",
        "reward_xp": 30,
        "reward_coins": 0,
        "reward_spins": 1,
    },
)


REFERRAL_SETTINGS = {
    "registration_reward_coins": 50,
    "registration_reward_xp": 25,
    "first_topup_reward_coins": 100,
    "first_subscription_reward_coins": 150,
    "max_visible_reward_text": "До 300 монет",
    "is_enabled": True,
}


class Command(BaseCommand):
    help = (
        "Create starter daily tasks, XP levels, streak rewards and referral bonus "
        "settings. Existing values are preserved unless --update is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update matching existing starter records with the command defaults.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        should_update = options["update"]
        counters = {"created": 0, "updated": 0, "skipped": 0}

        self._seed_daily_tasks(should_update, counters)
        self._seed_xp_levels(should_update, counters)
        self._seed_streak_rewards(should_update, counters)
        self._seed_referral_settings(should_update, counters)

        self.stdout.write(
            self.style.SUCCESS(
                "Бонусный центр заполнен: "
                f"создано {counters['created']}, "
                f"обновлено {counters['updated']}, "
                f"пропущено {counters['skipped']}."
            )
        )

    @staticmethod
    def _apply_defaults(instance, defaults, *, should_update, counters):
        if instance is None:
            counters["created"] += 1
            return None
        if not should_update:
            counters["skipped"] += 1
            return instance

        changed_fields = []
        for field, value in defaults.items():
            if getattr(instance, field) == value:
                continue
            setattr(instance, field, value)
            changed_fields.append(field)

        if changed_fields:
            instance.save(update_fields=changed_fields)
            counters["updated"] += 1
        else:
            counters["skipped"] += 1
        return instance

    def _seed_daily_tasks(self, should_update, counters):
        for data in DAILY_TASKS:
            lookup = {
                "task_type": data["task_type"],
                "audience": data["audience"],
            }
            defaults = {
                key: value
                for key, value in data.items()
                if key not in lookup
            }
            task = DailyTask.objects.filter(**lookup).order_by("id").first()
            if task is None:
                DailyTask.objects.create(
                    **lookup,
                    **defaults,
                    is_active=True,
                )
                counters["created"] += 1
                continue
            self._apply_defaults(
                task,
                {**defaults, "is_active": True},
                should_update=should_update,
                counters=counters,
            )

    def _seed_xp_levels(self, should_update, counters):
        for data in XP_LEVELS:
            level = XpLevel.objects.filter(level=data["level"]).first()
            defaults = {
                "title": data["title"],
                "required_xp": data["required_xp"],
                "reward_coins": 0,
                "reward_spins": 0,
                "is_active": True,
                "order": data["order"],
            }
            if level is None:
                XpLevel.objects.create(level=data["level"], **defaults)
                counters["created"] += 1
                continue
            self._apply_defaults(
                level,
                defaults,
                should_update=should_update,
                counters=counters,
            )

    def _seed_streak_rewards(self, should_update, counters):
        for data in STREAK_REWARDS:
            reward = StreakReward.objects.filter(
                day_number=data["day_number"],
            ).first()
            defaults = {
                key: value
                for key, value in data.items()
                if key != "day_number"
            }
            defaults["is_active"] = True
            if reward is None:
                StreakReward.objects.create(
                    day_number=data["day_number"],
                    **defaults,
                )
                counters["created"] += 1
                continue
            self._apply_defaults(
                reward,
                defaults,
                should_update=should_update,
                counters=counters,
            )

    def _seed_referral_settings(self, should_update, counters):
        settings_obj = ReferralBonusSettings.objects.filter(pk=1).first()
        if settings_obj is None:
            ReferralBonusSettings.objects.create(pk=1, **REFERRAL_SETTINGS)
            counters["created"] += 1
            return
        self._apply_defaults(
            settings_obj,
            REFERRAL_SETTINGS,
            should_update=should_update,
            counters=counters,
        )
