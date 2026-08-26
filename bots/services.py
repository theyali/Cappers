import random
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from bots.models import BotAccount, BotActionLog, BotExpertStrategy
from cabinet.models import AnalystFollow, AnalystProfile, User
from front.models import PredictionLike
from game.models import Match, Prediction, PredictionCoupon


READER_NAMES = [
    ("Ali Mammadov", "ali.mammadov"),
    ("Alexander Volkov", "alex.volkov"),
    ("Nikita Smirnov", "nikita.smirnov"),
    ("Murat Huseynov", "murat.huseynov"),
    ("Denis Larionov", "denis.larionov"),
    ("Ruslan Karimov", "ruslan.karimov"),
    ("Timur Aliyev", "timur.aliyev"),
    ("Igor Sokolov", "igor.sokolov"),
    ("Pavel Romanov", "pavel.romanov"),
    ("Vadim Abbasov", "vadim.abbasov"),
    ("Kirill Morozov", "kirill.morozov"),
    ("Matvey Sokolov", "matvey.sokolov"),
    ("Arman Petrosyan", "arman.petrosyan"),
    ("Gleb Fedorov", "gleb.fedorov"),
    ("Oleg Azimov", "oleg.azimov"),
    ("Roman Kim", "roman.kim"),
    ("Marat Ismayilov", "marat.ismayilov"),
    ("Vitaly Kuznetsov", "vitaly.kuznetsov"),
    ("Egor Zakharov", "egor.zakharov"),
    ("Anton Shakhov", "anton.shakhov"),
    ("Ilya Orlov", "ilya.orlov"),
    ("Maxim Nikolaev", "maxim.nikolaev"),
    ("Damir Safin", "damir.safin"),
    ("Artem Belyaev", "artem.belyaev"),
    ("Lev Klimov", "lev.klimov"),
    ("Danil Orlov", "danil.orlov"),
    ("Semen Markov", "semen.markov"),
    ("Vlad Kovalov", "vlad.kovalov"),
    ("Mikhail Kozlov", "mikhail.kozlov"),
    ("Boris Andreev", "boris.andreev"),
    ("Nazar Aghayev", "nazar.aghayev"),
    ("Eldar Hasanov", "eldar.hasanov"),
    ("Filipp Egorov", "filipp.egorov"),
    ("Stanislav Lebedev", "stanislav.lebedev"),
    ("Anatoly Mironov", "anatoly.mironov"),
    ("Yan Abramov", "yan.abramov"),
    ("Victor Pavlov", "victor.pavlov"),
    ("Nikolay Vasilev", "nikolay.vasilev"),
    ("Georgy Saveliev", "georgy.saveliev"),
    ("Luka Danilov", "luka.danilov"),
]

EXPERT_NAMES = [
    ("Aleksey Sorokin", "aleksey.sorokin"),
    ("Mark Voronov", "mark.voronov"),
    ("David Nazarov", "david.nazarov"),
    ("Ruslan Akhmedov", "ruslan.akhmedov"),
    ("Ilya Kuznetsov", "ilya.kuznetsov"),
    ("Timur Mammadov", "timur.mammadov"),
    ("Nikita Belyaev", "nikita.belyaev"),
    ("Roman Grigoriev", "roman.grigoriev"),
    ("Arsen Hakobyan", "arsen.hakobyan"),
    ("Denis Fedotov", "denis.fedotov"),
    ("Vadim Krylov", "vadim.krylov"),
    ("Kirill Pavlenko", "kirill.pavlenko"),
    ("Oleg Samoylov", "oleg.samoylov"),
    ("Marat Khalilov", "marat.khalilov"),
    ("Pavel Mironov", "pavel.mironov"),
    ("Gleb Antonov", "gleb.antonov"),
    ("Anton Zhuravlev", "anton.zhuravlev"),
    ("Damir Yusupov", "damir.yusupov"),
    ("Egor Makarov", "egor.makarov"),
    ("Maxim Orlov", "maxim.orlov"),
]

MARKET_ROTATION = ["winner", "total", "both_score", "double_chance", "handicap"]
COMMENTS = {
    "winner": [
        "Выбор по форме команд и качеству последних матчей.",
        "Команда стабильнее проходит давление и лучше реализует моменты.",
        "Ставка по балансу состава, мотивации и текущей динамике.",
    ],
    "total": [
        "Ожидаю открытый темп и достаточно моментов у обеих команд.",
        "По статистике команд линия тотала выглядит заниженной.",
        "Матч подходит под осторожный сценарий по голам.",
    ],
    "both_score": [
        "Обе команды регулярно создают моменты и допускают у своих ворот.",
        "Стили соперников дают хороший шанс на обмен голами.",
    ],
    "double_chance": [
        "Беру более спокойный вариант с защитой от ничьей.",
        "Форма команды позволяет страховать основной исход.",
    ],
    "handicap": [
        "Фора выглядит рабочей с учетом разницы в классе и календаря.",
        "Ожидаю плотный матч, поэтому фора дает лучший запас.",
    ],
}


@dataclass(frozen=True)
class Pick:
    market: str
    selection: str
    coefficient: Decimal
    comment: str


def seed_bots(reader_count: int = 40, expert_count: int = 20) -> dict:
    created_users = 0
    updated_bots = 0

    for index, item in enumerate(READER_NAMES[:reader_count], start=1):
        name, username = _name_pair(item)
        user, created = _bot_user(username, name, User.Role.READER)
        BotAccount.objects.update_or_create(
            user=user,
            defaults={
                "kind": BotAccount.Kind.READER,
                "persona": name,
                "is_active": True,
            },
        )
        created_users += int(created)
        updated_bots += 1

    for index, item in enumerate(EXPERT_NAMES[:expert_count], start=1):
        name, username = _name_pair(item)
        user, created = _bot_user(username, name, User.Role.ANALYST)
        profile, _ = AnalystProfile.objects.get_or_create(user=user)
        profile.display_name = name
        profile.bio = _expert_bio(index, name)
        profile.is_public = True
        profile.is_verified = index <= 6
        profile.save(update_fields=["display_name", "bio", "is_public", "is_verified", "updated_at"])

        bot, _ = BotAccount.objects.update_or_create(
            user=user,
            defaults={
                "kind": BotAccount.Kind.EXPERT,
                "persona": name,
                "is_active": True,
            },
        )
        BotExpertStrategy.objects.update_or_create(
            bot=bot,
            defaults=_strategy_defaults(index),
        )
        created_users += int(created)
        updated_bots += 1

    return {"created_users": created_users, "bots": updated_bots}


def run_bot_predictions(now=None) -> dict:
    now = now or timezone.now()
    strategies = BotExpertStrategy.objects.select_related("bot__user").filter(
        bot__is_active=True,
        bot__kind=BotAccount.Kind.EXPERT,
    ).filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))

    created = 0
    skipped = 0
    for strategy in strategies:
        count = random.randint(strategy.daily_predictions_min, strategy.daily_predictions_max)
        user_created = 0
        used_match_ids = set(
            Prediction.objects.filter(
                coupon__author=strategy.bot.user,
                coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                created_at__date=timezone.localdate(now),
            ).values_list("match_id", flat=True)
        )

        for _ in range(count):
            match = _next_match(strategy, used_match_ids)
            if match is None:
                skipped += 1
                continue
            pick = _pick_for_match(match, strategy)
            if pick is None:
                skipped += 1
                continue
            _create_prediction(strategy.bot, match, pick, now)
            used_match_ids.add(match.id)
            created += 1
            user_created += 1

        strategy.last_run_at = now
        strategy.next_run_at = now + timedelta(days=max(strategy.cadence_days, 1))
        strategy.save(update_fields=["last_run_at", "next_run_at"])
        if user_created:
            BotActionLog.objects.create(
                bot=strategy.bot,
                action=BotActionLog.Action.PREDICTION,
                target=f"{user_created} прогнозов",
                meta={"count": user_created},
            )

    return {"created": created, "skipped": skipped, "strategies": strategies.count()}


def run_bot_activity(max_actions: int = 80) -> dict:
    reader_bots = list(
        BotAccount.objects.select_related("user").filter(
            kind=BotAccount.Kind.READER,
            is_active=True,
        )
    )
    if not reader_bots:
        return {"actions": 0, "reason": "no_reader_bots"}

    actions = 0
    for _ in range(max_actions):
        bot = random.choice(reader_bots)
        if random.random() < 0.58:
            actions += int(_like_prediction(bot))
        else:
            actions += int(_follow_or_unfollow(bot))
    return {"actions": actions}


def create_history(days_back: int = 21, per_expert: int = 8) -> dict:
    created = 0
    finished_matches = list(
        Match.objects.select_related("league", "home_team", "away_team")
        .filter(sync_scope=Match.SyncScope.FINISHED)
        .order_by("-starts_at")[:300]
    )
    if not finished_matches:
        return {"created": 0, "reason": "no_finished_matches"}

    experts = BotExpertStrategy.objects.select_related("bot__user").filter(bot__is_active=True)
    for strategy in experts:
        for offset in range(per_expert):
            match = random.choice(finished_matches)
            if Prediction.objects.filter(coupon__author=strategy.bot.user, match=match).exists():
                continue
            pick = _fallback_pick(match, strategy)
            created_at = timezone.now() - timedelta(days=random.randint(1, max(days_back, 1)))
            prediction = _create_prediction(strategy.bot, match, pick, created_at, settled=True)
            outcome = random.choices(
                [Prediction.StateStatus.WIN, Prediction.StateStatus.LOSE, Prediction.StateStatus.REFUND],
                weights=[52, 38, 10],
                k=1,
            )[0]
            prediction.state_status = outcome
            prediction.save(update_fields=["state_status", "updated_at"])
            created += 1
    return {"created": created}


def _bot_user(username: str, full_name: str, role: str) -> tuple[User, bool]:
    first_name, _, last_name = full_name.partition(" ")
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "first_name": first_name,
            "last_name": last_name,
            "email": f"{username}@bots.cappers.local",
            "role": role,
        },
    )
    changed_fields = []
    for field, value in {
        "first_name": first_name,
        "last_name": last_name,
        "email": f"{username}@bots.cappers.local",
        "role": role,
    }.items():
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed_fields.append(field)
    if created:
        user.set_unusable_password()
        changed_fields.append("password")
    if changed_fields:
        user.save(update_fields=changed_fields)
    return user, created


def _name_pair(item) -> tuple[str, str]:
    if isinstance(item, tuple):
        return item
    return str(item), str(item).lower().replace(" ", ".")


def _strategy_defaults(index: int) -> dict:
    cadence = 3 if index % 5 == 0 else (2 if index % 4 == 0 else 1)
    return {
        "cadence_days": cadence,
        "daily_predictions_min": 1,
        "daily_predictions_max": 2 if index % 3 != 0 else 1,
        "market_preference": MARKET_ROTATION[(index - 1) % len(MARKET_ROTATION)],
        "risk_profile": (
            BotExpertStrategy.RiskProfile.AGGRESSIVE
            if index % 6 == 0
            else BotExpertStrategy.RiskProfile.SAFE
            if index % 4 == 0
            else BotExpertStrategy.RiskProfile.BALANCED
        ),
        "next_run_at": timezone.now() - timedelta(minutes=random.randint(5, 180)),
    }


def _expert_bio(index: int, name: str) -> str:
    focuses = ["исходам", "тоталам", "форме команд", "молодежным лигам", "коэффициентам до матча"]
    return f"{name} разбирает футбол по {focuses[index % len(focuses)]} и публикует краткие прогнозы перед матчами."


def _next_match(strategy: BotExpertStrategy, used_match_ids: set[int]) -> Match | None:
    queryset = (
        Match.objects.select_related("odds", "league", "home_team", "away_team")
        .filter(sync_scope=Match.SyncScope.PREMATCH, starts_at__gt=timezone.now())
        .exclude(id__in=used_match_ids)
        .filter(odds__home_win_bet__isnull=False)
        .order_by("starts_at", "id")
    )
    if strategy.risk_profile == BotExpertStrategy.RiskProfile.AGGRESSIVE:
        queryset = queryset.filter(odds__home_win_bet__gte=Decimal("1.6"))
    return queryset[random.randrange(min(queryset.count(), 80))] if queryset.exists() else None


def _pick_for_match(match: Match, strategy: BotExpertStrategy) -> Pick | None:
    options = _available_picks(match)
    if not options:
        return None
    preferred = [pick for pick in options if pick.market == strategy.market_preference]
    source = preferred or options
    if strategy.risk_profile == BotExpertStrategy.RiskProfile.SAFE:
        source = sorted(source, key=lambda item: abs(item.coefficient - Decimal("1.65")))
        return source[0]
    if strategy.risk_profile == BotExpertStrategy.RiskProfile.AGGRESSIVE:
        source = sorted(source, key=lambda item: item.coefficient, reverse=True)
        return source[0]
    return random.choice(source[: min(len(source), 4)])


def _available_picks(match: Match) -> list[Pick]:
    try:
        odds = match.odds
    except Match.odds.RelatedObjectDoesNotExist:
        return []

    home = match.home_team_name or "Хозяева"
    away = match.away_team_name or "Гости"
    raw = [
        ("winner", home, odds.home_win_bet),
        ("winner", "Ничья", odds.x_bet),
        ("winner", away, odds.away_win_bet),
        ("total", "ТБ 2.5", odds.goals_over_2_5),
        ("total", "ТМ 2.5", odds.goals_under_2_5),
        ("both_score", "Обе забьют: да", odds.btts_yes),
        ("both_score", "Обе забьют: нет", odds.btts_no),
        ("double_chance", f"{home} или ничья", odds.d_1x),
        ("double_chance", f"Ничья или {away}", odds.d_2x),
        ("handicap", f"{home} фора 0", odds.fora_1_0),
        ("handicap", f"{away} фора 0", odds.fora_2_0),
    ]
    picks = []
    for market, selection, value in raw:
        coefficient = _coefficient(value)
        if coefficient is None:
            continue
        picks.append(
            Pick(
                market=market,
                selection=selection,
                coefficient=coefficient,
                comment=random.choice(COMMENTS.get(market, COMMENTS["winner"])),
            )
        )
    return picks


def _fallback_pick(match: Match, strategy: BotExpertStrategy) -> Pick:
    home = match.home_team_name or "Хозяева"
    away = match.away_team_name or "Гости"
    market = strategy.market_preference
    if market == "total":
        selection = random.choice(["ТБ 2.5", "ТМ 2.5"])
    elif market == "both_score":
        selection = random.choice(["Обе забьют: да", "Обе забьют: нет"])
    elif market == "double_chance":
        selection = random.choice([f"{home} или ничья", f"Ничья или {away}"])
    elif market == "handicap":
        selection = random.choice([f"{home} фора 0", f"{away} фора 0"])
    else:
        market = "winner"
        selection = random.choice([home, "Ничья", away])
    return Pick(
        market=market,
        selection=selection,
        coefficient=Decimal(str(random.choice(["1.55", "1.70", "1.85", "2.05", "2.30"]))),
        comment=random.choice(COMMENTS.get(market, COMMENTS["winner"])),
    )


@transaction.atomic
def _create_prediction(
    bot: BotAccount,
    match: Match,
    pick: Pick,
    published_at,
    *,
    settled: bool = False,
) -> Prediction:
    if Prediction.objects.filter(coupon__author=bot.user, match=match).exists():
        return Prediction.objects.filter(coupon__author=bot.user, match=match).first()

    stake = Decimal(str(random.choice([50, 75, 100, 150, 200, 250, 300])))
    coupon = PredictionCoupon(
        author=bot.user,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        total_stake=stake,
        possible_payout=(stake * pick.coefficient).quantize(Decimal("0.01")),
        published_at=published_at,
    )
    if hasattr(coupon, "title"):
        coupon.title = _coupon_title(match, pick)
    coupon.save()
    prediction = Prediction.objects.create(
        coupon=coupon,
        match=match,
        market=pick.market,
        selection=pick.selection,
        coefficient=pick.coefficient,
        stake=stake,
        comment=pick.comment,
        state_status="" if not settled else Prediction.StateStatus.WIN,
    )
    BotActionLog.objects.create(
        bot=bot,
        action=BotActionLog.Action.PREDICTION,
        target=str(prediction.id),
        meta={"match": match.id, "market": pick.market, "selection": pick.selection},
    )
    return prediction


def _like_prediction(bot: BotAccount) -> bool:
    prediction_ids = list(
        Prediction.objects.filter(
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .exclude(coupon__author=bot.user)
        .order_by("-created_at")
        .values_list("id", flat=True)[:120]
    )
    if not prediction_ids:
        return False
    prediction_id = random.choice(prediction_ids)
    like, created = PredictionLike.objects.get_or_create(
        user=bot.user,
        prediction_id=prediction_id,
    )
    if not created and random.random() < 0.08:
        like.delete()
        BotActionLog.objects.create(bot=bot, action=BotActionLog.Action.UNLIKE, target=str(prediction_id))
        return True
    if created:
        BotActionLog.objects.create(bot=bot, action=BotActionLog.Action.LIKE, target=str(prediction_id))
    return created


def _follow_or_unfollow(bot: BotAccount) -> bool:
    analyst_ids = list(
        User.objects.filter(role=User.Role.ANALYST, analyst_profile__is_public=True)
        .exclude(pk=bot.user_id)
        .values_list("id", flat=True)
    )
    if not analyst_ids:
        return False
    analyst_id = random.choice(analyst_ids)
    follow, created = AnalystFollow.objects.get_or_create(
        follower=bot.user,
        analyst_id=analyst_id,
    )
    if not created and random.random() < 0.18:
        follow.delete()
        BotActionLog.objects.create(bot=bot, action=BotActionLog.Action.UNFOLLOW, target=str(analyst_id))
        return True
    if created:
        BotActionLog.objects.create(bot=bot, action=BotActionLog.Action.FOLLOW, target=str(analyst_id))
    return created


def _coefficient(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        coefficient = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return None
    return coefficient if coefficient > 0 else None


def _coupon_title(match: Match, pick: Pick) -> str:
    return " · ".join(
        part
        for part in [
            f"{match.home_team_name} — {match.away_team_name}",
            match.league_name,
            pick.selection,
        ]
        if part
    )[:160]
