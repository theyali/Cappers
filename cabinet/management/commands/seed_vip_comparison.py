from django.core.management.base import BaseCommand
from django.db import transaction

from cabinet.models import (
    VipPlan,
    VipPlanComparisonFeature,
    VipPlanComparisonValue,
)


FEATURES = (
    {
        "title": "Доступ к VIP прогнозам",
        "order": 10,
        "values": {
            1: {"value_text": "Базовый доступ"},
            2: {"value_text": "Полный доступ"},
            3: {"value_text": "Полный доступ"},
        },
    },
    {
        "title": "Расширенная статистика",
        "order": 20,
        "values": {
            1: {"value_text": "Ограниченная"},
            2: {"value_text": "Полная"},
            3: {"value_text": "Полная + эксклюзивная"},
        },
    },
    {
        "title": "Ранний доступ к прогнозам",
        "order": 30,
        "values": {
            1: {"value_text": "-"},
            2: {"is_checked": True},
            3: {"is_checked": True},
        },
    },
    {
        "title": "Повышенные лимиты",
        "order": 40,
        "values": {
            1: {"value_text": "До 10 прогнозов в день"},
            2: {"value_text": "До 30 прогнозов в день"},
            3: {"value_text": "Без ограничений"},
        },
    },
    {
        "title": "Приоритетная поддержка",
        "order": 50,
        "values": {
            1: {"value_text": "-"},
            2: {"is_checked": True},
            3: {"is_checked": True},
        },
    },
    {
        "title": "Эксклюзивные материалы",
        "order": 60,
        "values": {
            1: {"value_text": "-"},
            2: {"is_checked": True},
            3: {"is_checked": True},
        },
    },
    {
        "title": "Персональные акции",
        "order": 70,
        "values": {
            1: {"value_text": "-"},
            2: {"value_text": "-"},
            3: {"is_checked": True},
        },
    },
    {
        "title": "Личный менеджер",
        "order": 80,
        "values": {
            1: {"value_text": "-"},
            2: {"value_text": "-"},
            3: {"is_checked": True},
        },
    },
)


class Command(BaseCommand):
    help = (
        "Seed VIP comparison table rows and values for existing VIP plans with "
        "order=1, order=2 and order=3. The command is idempotent."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        plans_by_order = {
            plan.order: plan
            for plan in VipPlan.objects.filter(order__in=(1, 2, 3)).order_by("order", "id")
        }

        missing_orders = [order for order in (1, 2, 3) if order not in plans_by_order]
        for order in missing_orders:
            self.stdout.write(
                self.style.WARNING(
                    f"VIP-тариф с order={order} не найден, значения для него пропущены."
                )
            )

        counters = {"features_created": 0, "features_updated": 0, "values_created": 0, "values_updated": 0}

        for feature_data in FEATURES:
            feature, created = VipPlanComparisonFeature.objects.update_or_create(
                title=feature_data["title"],
                defaults={
                    "order": feature_data["order"],
                    "is_active": True,
                },
            )
            if created:
                counters["features_created"] += 1
            else:
                counters["features_updated"] += 1

            for plan_order, value_data in feature_data["values"].items():
                plan = plans_by_order.get(plan_order)
                if plan is None:
                    continue

                defaults = {
                    "value_text": value_data.get("value_text", ""),
                    "is_checked": value_data.get("is_checked", False),
                }
                _, value_created = VipPlanComparisonValue.objects.update_or_create(
                    feature=feature,
                    plan=plan,
                    defaults=defaults,
                )
                if value_created:
                    counters["values_created"] += 1
                else:
                    counters["values_updated"] += 1

        self.stdout.write(
            self.style.SUCCESS(
                "VIP comparison seeded: "
                f"features created={counters['features_created']}, "
                f"features updated={counters['features_updated']}, "
                f"values created={counters['values_created']}, "
                f"values updated={counters['values_updated']}."
            )
        )
