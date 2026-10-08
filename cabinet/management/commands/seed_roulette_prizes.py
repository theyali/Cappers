from django.core.management.base import BaseCommand
from django.db import transaction

from cabinet.roulette.models import RoulettePrize, RoulettePrizeCondition

Reward = RoulettePrize.RewardType
Audience = RoulettePrizeCondition.ConditionType

# Wheel prizes by audience; no conditions means everyone. The wheel shows at most
# 10 sectors, and every mix stays within that: a reader, a VIP reader and a capper
# see 8 sectors, a VIP capper 10. Sector order alternates big and small prizes.
# Rating boost is left out: nothing on the site uses it yet. Free predictions go to
# cappers only, since only they write coupons.
ROULETTE_PRIZES = (
    {
        "title": "50 коинов",
        "short_text": "Коины сразу на баланс",
        "reward_type": Reward.COINS,
        "reward_value": 50,
        "weight": 30,
        "sector_order": 10,
        "audience": (),
    },
    {
        "title": "100 коинов",
        "short_text": "Коины сразу на баланс",
        "reward_type": Reward.COINS,
        "reward_value": 100,
        "weight": 18,
        "sector_order": 20,
        "audience": (Audience.READERS_ONLY,),
    },
    {
        "title": "200 коинов",
        "short_text": "Коины сразу на баланс",
        "reward_type": Reward.COINS,
        "reward_value": 200,
        "weight": 18,
        "sector_order": 30,
        "audience": (Audience.ANALYSTS_ONLY,),
    },
    {
        "title": "Пусто",
        "short_text": "Повезёт в следующий раз",
        "reward_type": Reward.NOTHING,
        "reward_value": 0,
        "weight": 20,
        "sector_order": 40,
        "audience": (),
    },
    {
        "title": "+3 дня VIP",
        "short_text": "VIP продлевается на 3 дня",
        "reward_type": Reward.VIP_DAYS,
        "reward_value": 3,
        "weight": 4,
        "sector_order": 50,
        "audience": (Audience.VIP_ONLY,),
    },
    {
        "title": "VIP на 1 день",
        "short_text": "Попробуйте VIP бесплатно",
        "reward_type": Reward.VIP_DAYS,
        "reward_value": 1,
        "weight": 5,
        "sector_order": 60,
        "audience": (Audience.READERS_ONLY, Audience.WITHOUT_VIP),
    },
    {
        "title": "1 бесплатный прогноз",
        "short_text": "Купон без ставки из баланса",
        "reward_type": Reward.FREE_PREDICTIONS,
        "reward_value": 1,
        "weight": 12,
        "sector_order": 70,
        "audience": (Audience.ANALYSTS_ONLY,),
    },
    {
        "title": "+1 попытка",
        "short_text": "Ещё одна прокрутка",
        "reward_type": Reward.EXTRA_SPIN,
        "reward_value": 1,
        "weight": 8,
        "sector_order": 80,
        "audience": (),
    },
    {
        "title": "VIP на 3 дня",
        "short_text": "Попробуйте VIP бесплатно",
        "reward_type": Reward.VIP_DAYS,
        "reward_value": 3,
        "weight": 2,
        "sector_order": 90,
        "audience": (Audience.READERS_ONLY, Audience.WITHOUT_VIP),
    },
    {
        "title": "3 бесплатных прогноза",
        "short_text": "Купоны без ставки из баланса",
        "reward_type": Reward.FREE_PREDICTIONS,
        "reward_value": 3,
        "weight": 4,
        "sector_order": 100,
        "audience": (Audience.ANALYSTS_ONLY,),
    },
    {
        "title": "400 коинов",
        "short_text": "Подарок для VIP",
        "reward_type": Reward.COINS,
        "reward_value": 400,
        "weight": 8,
        "sector_order": 110,
        "audience": (Audience.VIP_ONLY,),
    },
    {
        "title": "300 коинов",
        "short_text": "Коины сразу на баланс",
        "reward_type": Reward.COINS,
        "reward_value": 300,
        "weight": 4,
        "sector_order": 120,
        "audience": (),
    },
    {
        "title": "150 коинов",
        "short_text": "Коины сразу на баланс",
        "reward_type": Reward.COINS,
        "reward_value": 150,
        "weight": 10,
        "sector_order": 130,
        "audience": (Audience.READERS_ONLY,),
    },
    {
        "title": "500 коинов",
        "short_text": "Крупный приз для капперов",
        "reward_type": Reward.COINS,
        "reward_value": 500,
        "weight": 3,
        "sector_order": 140,
        "audience": (Audience.ANALYSTS_ONLY,),
    },
)


class Command(BaseCommand):
    help = (
        "Create the bonus wheel prizes for everyone, readers, cappers and VIP users. "
        "Prizes that already exist under the same title are kept unless --update is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--update",
            action="store_true",
            help="Bring existing prizes with the same titles back to this set, audience included.",
        )
        parser.add_argument(
            "--disable-other-prizes",
            action="store_true",
            help="Switch off wheel prizes that are not in this set, so the wheel shows only them.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        counters = {"created": 0, "updated": 0, "skipped": 0}
        seeded_ids = []
        for data in ROULETTE_PRIZES:
            fields = {key: value for key, value in data.items() if key not in ("title", "audience")}
            fields["is_active"] = True
            fields["condition_logic"] = RoulettePrize.ConditionLogic.ALL
            prize = RoulettePrize.objects.filter(title=data["title"]).order_by("id").first()
            if prize is None:
                prize = RoulettePrize(title=data["title"], **fields)
                counters["created"] += 1
            elif options["update"]:
                for field, value in fields.items():
                    setattr(prize, field, value)
                counters["updated"] += 1
            else:
                counters["skipped"] += 1
                seeded_ids.append(prize.pk)
                continue
            prize.full_clean()
            prize.save()
            self._set_audience(prize, data["audience"])
            seeded_ids.append(prize.pk)

        self.stdout.write(
            self.style.SUCCESS(
                "Призы колеса: "
                f"создано {counters['created']}, "
                f"обновлено {counters['updated']}, "
                f"оставлено как было {counters['skipped']}."
            )
        )
        if counters["skipped"]:
            self.stdout.write(
                "Призы с такими названиями уже были и не изменены; "
                "чтобы привести их к этому набору, запустите команду с --update."
            )

        others = RoulettePrize.objects.filter(is_active=True).exclude(pk__in=seeded_ids)
        if options["disable_other_prizes"]:
            switched_off = others.update(is_active=False)
            if switched_off:
                self.stdout.write(f"Выключено других призов колеса: {switched_off}.")
        elif others.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Кроме этого набора включено ещё призов колеса: {others.count()}. "
                    "Колесо показывает не больше 10 секторов; чтобы оставить только "
                    "этот набор, запустите команду с --disable-other-prizes."
                )
            )

    @staticmethod
    def _set_audience(prize, condition_types):
        prize.conditions.exclude(condition_type__in=condition_types).delete()
        for order, condition_type in enumerate(condition_types):
            RoulettePrizeCondition.objects.update_or_create(
                prize=prize,
                condition_type=condition_type,
                defaults={"threshold": None, "is_active": True, "order": order},
            )
