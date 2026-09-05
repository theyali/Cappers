import random
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.db.models import F, Q
from django.utils import timezone

from bots.models import (
    BotAccount,
    BotActionLog,
    BotExpertStrategy,
    BotOnlineSession,
    BotPlannedAction,
    BotRuntimeControl,
)
from cabinet.models import AnalystFollow, AnalystProfile, User
from cabinet.presence import UserPresence
from front.models import PredictionLike
from game.models import Match, Prediction, PredictionCoupon
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant, TournamentPredictionEntry
from tournaments.services.join import TournamentJoinError, join_tournament
from tournaments.services.rules import TournamentRuleError, validate_tournament_coupon


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

MARKET_WEIGHTS = {
    "winner": 34,
    "total": 26,
    "double_chance": 16,
    "both_score": 14,
    "handicap": 10,
}
BOT_SPORT_FOCUS_ROTATION = (
    ("football",),
    ("football", "tennis"),
    ("football", "basketball"),
    ("tennis",),
    ("hockey", "football"),
)
SINGLE_COEFFICIENT_RANGES = {
    BotExpertStrategy.RiskProfile.SAFE: (Decimal("1.25"), Decimal("2.20")),
    BotExpertStrategy.RiskProfile.BALANCED: (Decimal("1.30"), Decimal("3.20")),
    BotExpertStrategy.RiskProfile.AGGRESSIVE: (Decimal("1.45"), Decimal("4.50")),
}
EXPRESS_LEG_COEFFICIENT_RANGE = (Decimal("1.25"), Decimal("2.35"))
EXPRESS_TOTAL_COEFFICIENT_RANGE = (Decimal("1.80"), Decimal("8.00"))
EXPRESS_SIZE_CHOICES = [2, 2, 3]
RECENT_EXPRESS_LOOKBACK = timedelta(days=7)
RECENT_PREDICTION_LOOKBACK = timedelta(hours=48)
MAX_MATCH_CHOICES = 120
MAX_PICK_ATTEMPTS_MULTIPLIER = 8
TOP_SCORED_CANDIDATE_POOL = 8
BOT_MIN_MINUTES_BETWEEN_COUPONS = 35
BOT_MAX_MINUTES_BETWEEN_COUPONS = 180
BOT_MIN_MINUTES_TO_MATCH_START = 45
BOT_PREDICTION_PLAN_DELAY_MINUTES_RANGE = (3, 75)
BOT_READER_ACTION_PLAN_DELAY_MINUTES_RANGE = (1, 35)
BOT_PLANNED_ACTION_STALE_AFTER = timedelta(minutes=30)
BOT_SESSION_DURATION_MINUTES_RANGE = (5, 40)
BOT_SESSION_TARGET_ACTION_WEIGHTS = (58, 32, 10)
BOT_MIN_MINUTES_BETWEEN_SESSIONS = 45
BOT_TOURNAMENT_JOIN_PROBABILITY = 0.25
BOT_TOURNAMENT_MAX_JOINS_PER_RUN = 3
BOT_TOURNAMENT_MAX_COUPONS_PER_RUN = 2
BOT_TOURNAMENT_MIN_MINUTES_AFTER_JOIN = 30
BOT_TOURNAMENT_MIN_HOURS_BETWEEN_COUPONS = 8
BOT_PRESENCE_ONLINE_SHARE_RANGE = (0.16, 0.32)
BOT_PRESENCE_RECENT_SHARE_RANGE = (0.24, 0.42)
BOT_PRESENCE_RECENT_MINUTES_RANGE = (7, 180)
BOT_PLANNED_ACTION_CLEANUP_DAYS = 14
BOT_ONLINE_SESSION_CLEANUP_DAYS = 14
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
        profile.telegram_channel = _telegram_channel(username)
        profile.telegram_account = _telegram_account(username)
        profile.is_public = True
        profile.is_verified = index <= 6
        profile.save(
            update_fields=[
                "display_name",
                "bio",
                "telegram_channel",
                "telegram_account",
                "is_public",
                "is_verified",
                "updated_at",
            ]
        )

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


def set_bot_runtime_mode(mode: str, *, note: str = "") -> dict:
    valid_modes = {choice for choice, _ in BotRuntimeControl.Mode.choices}
    if mode not in valid_modes:
        return {"updated": False, "reason": "invalid_mode", "mode": mode}
    control = BotRuntimeControl.load()
    control.mode = mode
    control.note = note
    control.save(update_fields=["mode", "note", "updated_at"])
    mode_value = control.mode.value if hasattr(control.mode, "value") else control.mode
    return {"updated": True, "mode": mode_value, "note": control.note}


def get_bot_runtime_status() -> dict:
    control = _runtime_control()
    mode = control.mode.value if hasattr(control.mode, "value") else control.mode
    return {
        "mode": mode,
        "note": control.note,
        "enabled": {
            "predictions": _runtime_feature_enabled("predictions", control=control),
            "reader_activity": _runtime_feature_enabled("reader_activity", control=control),
            "presence": _runtime_feature_enabled("presence", control=control),
            "tournaments": _runtime_feature_enabled("tournaments", control=control),
        },
    }


def _runtime_control() -> BotRuntimeControl:
    try:
        return BotRuntimeControl.load()
    except (OperationalError, ProgrammingError):
        return BotRuntimeControl(mode=BotRuntimeControl.Mode.ALL)


def _runtime_feature_enabled(feature: str, *, control: BotRuntimeControl | None = None) -> bool:
    control = control or _runtime_control()
    if control.mode == BotRuntimeControl.Mode.ALL:
        return True
    if control.mode == BotRuntimeControl.Mode.PAUSED:
        return False
    if control.mode == BotRuntimeControl.Mode.PRESENCE_ONLY:
        return feature == "presence"
    if control.mode == BotRuntimeControl.Mode.TOURNAMENTS_ONLY:
        return feature == "tournaments"
    return True


def run_bot_predictions(now=None, *, execute_immediately: bool = False) -> dict:
    now = now or timezone.now()
    if not _runtime_feature_enabled("predictions"):
        return {"planned": 0, "skipped": 0, "strategies": 0, "reason": "bot_runtime_disabled"}
    if execute_immediately:
        return _run_due_bot_predictions_immediately(now)

    strategies = list(
        BotExpertStrategy.objects.select_related("bot__user")
        .filter(
            bot__is_active=True,
            bot__kind=BotAccount.Kind.EXPERT,
        )
        .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
    )

    planned = 0
    skipped = 0
    skip_reasons = Counter()
    for strategy in strategies:
        daily_count = _published_bot_coupons_today(strategy, now)
        if daily_count >= strategy.daily_predictions_max:
            skipped += 1
            skip_reasons["daily_limit_reached"] += 1
            _reschedule_strategy(strategy, now, reached_daily_limit=True)
            continue

        if BotPlannedAction.objects.filter(
            bot=strategy.bot,
            action=BotPlannedAction.Action.PREDICTION,
            status=BotPlannedAction.Status.PENDING,
        ).exists():
            skipped += 1
            skip_reasons["already_planned"] += 1
            continue

        scheduled_at = now + timedelta(
            minutes=random.randint(*BOT_PREDICTION_PLAN_DELAY_MINUTES_RANGE),
            seconds=random.randint(0, 59),
        )
        if _create_planned_action(
            bot=strategy.bot,
            action=BotPlannedAction.Action.PREDICTION,
            scheduled_at=scheduled_at,
            payload={"strategy_id": strategy.id},
        ):
            planned += 1
        else:
            skipped += 1
            skip_reasons["already_planned"] += 1
            continue
        _reschedule_strategy(
            strategy,
            now,
            reached_daily_limit=daily_count + 1 >= strategy.daily_predictions_max,
        )

    return {
        "planned": planned,
        "skipped": skipped,
        "strategies": len(strategies),
        "skip_reasons": dict(skip_reasons),
    }


def preview_bot_predictions(now=None, *, limit: int = 10) -> dict:
    now = now or timezone.now()
    strategies = list(
        BotExpertStrategy.objects.select_related("bot__user")
        .filter(
            bot__is_active=True,
            bot__kind=BotAccount.Kind.EXPERT,
        )
        .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
    )
    taken_picks = _recent_taken_picks(now)
    previews = []
    skipped = 0
    skip_reasons = Counter()

    for strategy in strategies:
        if len(previews) >= limit:
            break
        daily_count = _published_bot_coupons_today(strategy, now)
        if daily_count >= strategy.daily_predictions_max:
            skipped += 1
            skip_reasons["daily_limit_reached"] += 1
            continue

        used_match_ids = set(
            Prediction.objects.filter(
                coupon__author=strategy.bot.user,
                match__sync_scope=Match.SyncScope.PREMATCH,
                match__starts_at__gt=now,
            ).values_list("match_id", flat=True)
        )
        express_first = random.random() < _express_probability(strategy, now=now)
        items = (
            _build_express_items(strategy, used_match_ids, taken_picks, now)
            if express_first
            else []
        )
        if not items:
            items = _build_single_items(strategy, used_match_ids, taken_picks, now)
        if not items:
            skipped += 1
            skip_reasons["no_reasonable_pick"] += 1
            continue

        for match, pick in items:
            taken_picks.add(_pick_key(match.id, pick.market, pick.selection))
        previews.append(
            {
                "bot": strategy.bot.user.username,
                "risk": strategy.risk_profile,
                "focus_sports": list(_strategy_focus_sports(strategy)),
                "coupon_type": _coupon_type_for_items(items),
                "total_coefficient": str(_total_coefficient([pick.coefficient for _, pick in items])),
                "positions": [
                    {
                        "match": _match_title(match),
                        "starts_at": match.starts_at.isoformat(),
                        "sport": match.sport_code,
                        "market": pick.market,
                        "selection": pick.selection,
                        "coefficient": str(pick.coefficient),
                    }
                    for match, pick in items
                ],
            }
        )

    return {
        "previews": previews,
        "strategies": len(strategies),
        "skipped": skipped,
        "skip_reasons": dict(skip_reasons),
    }


def _run_due_bot_predictions_immediately(now=None) -> dict:
    now = now or timezone.now()
    strategies = list(
        BotExpertStrategy.objects.select_related("bot__user")
        .filter(
            bot__is_active=True,
            bot__kind=BotAccount.Kind.EXPERT,
        )
        .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
    )
    taken_picks = _recent_taken_picks(now)
    created = 0
    skipped = 0
    skip_reasons = Counter()
    for strategy in strategies:
        created_coupon, reason, coupon = _execute_strategy_prediction(
            strategy,
            now,
            taken_picks=taken_picks,
        )
        if created_coupon:
            created += 1
        else:
            skipped += 1
            skip_reasons[reason] += 1

        daily_count = _published_bot_coupons_today(strategy, now)
        _reschedule_strategy(
            strategy,
            now,
            reached_daily_limit=daily_count >= strategy.daily_predictions_max,
            no_pick=reason == "no_reasonable_pick",
        )

    return {
        "created": created,
        "skipped": skipped,
        "strategies": len(strategies),
        "skip_reasons": dict(skip_reasons),
    }


def _execute_strategy_prediction(
    strategy: BotExpertStrategy,
    now,
    *,
    taken_picks: set[tuple[int, str, str]] | None = None,
) -> tuple[bool, str, PredictionCoupon | None]:
    taken_picks = taken_picks if taken_picks is not None else _recent_taken_picks(now)
    daily_count = _published_bot_coupons_today(strategy, now)
    if daily_count >= strategy.daily_predictions_max:
        return False, "daily_limit_reached", None

    used_match_ids = set(
        Prediction.objects.filter(
            coupon__author=strategy.bot.user,
            match__sync_scope=Match.SyncScope.PREMATCH,
            match__starts_at__gt=now,
        ).values_list("match_id", flat=True)
    )

    items = []
    if random.random() < _express_probability(strategy, now=now):
        items = _build_express_items(strategy, used_match_ids, taken_picks, now)
    if not items:
        items = _build_single_items(strategy, used_match_ids, taken_picks, now)

    if not items:
        return False, "no_reasonable_pick", None

    coupon, predictions, was_created = _create_coupon(strategy.bot, items, now)
    if not was_created:
        return False, "already_predicted", None

    for prediction in predictions:
        taken_picks.add(_pick_key(prediction.match_id, prediction.market, prediction.selection))
    BotActionLog.objects.create(
        bot=strategy.bot,
        action=BotActionLog.Action.PREDICTION,
        target=f"Купон #{coupon.id}",
        meta={
            "coupon": coupon.id,
            "coupon_type": coupon.coupon_type,
            "positions": len(predictions),
            "total_coefficient": str(_total_coefficient([prediction.coefficient for prediction in predictions])),
        },
    )
    return True, "created", coupon


def run_bot_planned_actions(now=None, *, max_actions: int = 30) -> dict:
    now = now or timezone.now()
    control = _runtime_control()
    enabled_actions = []
    if _runtime_feature_enabled("predictions", control=control):
        enabled_actions.append(BotPlannedAction.Action.PREDICTION)
    if _runtime_feature_enabled("reader_activity", control=control):
        enabled_actions.append(BotPlannedAction.Action.READER_ACTIVITY)
    if _runtime_feature_enabled("tournaments", control=control):
        enabled_actions.append(BotPlannedAction.Action.TOURNAMENT_ACTIVITY)
    if not enabled_actions:
        return {
            "due": 0,
            "executed": 0,
            "skipped": 0,
            "failed": 0,
            "recovered": 0,
            "reason": "bot_runtime_disabled",
        }

    recovered = BotPlannedAction.objects.filter(
        status=BotPlannedAction.Status.RUNNING,
        started_at__lt=now - BOT_PLANNED_ACTION_STALE_AFTER,
    ).update(
        status=BotPlannedAction.Status.PENDING,
        started_at=None,
        error="",
        updated_at=now,
    )
    actions = list(
        BotPlannedAction.objects
        .filter(
            status=BotPlannedAction.Status.PENDING,
            scheduled_at__lte=now,
            action__in=enabled_actions,
        )
        .values_list("id", flat=True)
        .order_by("scheduled_at", "id")[:max_actions]
    )
    executed = 0
    skipped = 0
    failed = 0
    reasons = Counter()

    for action_id in actions:
        with transaction.atomic():
            action = (
                BotPlannedAction.objects.select_for_update(of=("self",))
                .select_related("bot", "bot__user")
                .filter(pk=action_id, status=BotPlannedAction.Status.PENDING)
                .first()
            )
            if action is None:
                continue
            action.status = BotPlannedAction.Status.RUNNING
            action.started_at = now
            action.save(update_fields=["status", "started_at", "updated_at"])

        try:
            done, reason, result = _execute_planned_action(action, now)
        except Exception as exc:
            action.status = BotPlannedAction.Status.FAILED
            action.error = str(exc)[:2000]
            action.finished_at = timezone.now()
            action.save(update_fields=["status", "error", "finished_at", "updated_at"])
            failed += 1
            reasons["exception"] += 1
            if action.bot_id and action.action == BotPlannedAction.Action.PREDICTION:
                BotActionLog.objects.create(
                    bot=action.bot,
                    action=BotActionLog.Action.PREDICTION,
                    target=f"Ошибка очереди #{action.id}",
                    meta={"planned_action": action.id, "action": action.action, "error": action.error},
                )
            continue

        action.status = (
            BotPlannedAction.Status.DONE
            if done
            else BotPlannedAction.Status.SKIPPED
        )
        action.result = result
        action.error = "" if done else reason
        action.finished_at = timezone.now()
        action.save(update_fields=["status", "result", "error", "finished_at", "updated_at"])
        executed += int(done)
        skipped += int(not done)
        reasons[reason] += 1
        if action.bot_id and action.action == BotPlannedAction.Action.PREDICTION and not done:
            BotActionLog.objects.create(
                bot=action.bot,
                action=BotActionLog.Action.PREDICTION,
                target=f"Пропуск очереди #{action.id}",
                meta={"planned_action": action.id, "action": action.action, "reason": reason},
            )

    return {
        "due": len(actions),
        "executed": executed,
        "skipped": skipped,
        "failed": failed,
        "recovered": recovered,
        "reasons": dict(reasons),
    }


def reset_stale_bot_planned_actions(now=None, *, older_minutes: int = 30) -> dict:
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=max(1, older_minutes))
    reset = BotPlannedAction.objects.filter(
        status=BotPlannedAction.Status.RUNNING,
        started_at__lt=cutoff,
    ).update(
        status=BotPlannedAction.Status.PENDING,
        started_at=None,
        error="",
        updated_at=now,
    )
    return {"reset": reset, "older_minutes": older_minutes}


def cleanup_bot_runtime_data(
    now=None,
    *,
    planned_days: int = BOT_PLANNED_ACTION_CLEANUP_DAYS,
    sessions_days: int = BOT_ONLINE_SESSION_CLEANUP_DAYS,
) -> dict:
    now = now or timezone.now()
    planned_cutoff = now - timedelta(days=max(1, planned_days))
    sessions_cutoff = now - timedelta(days=max(1, sessions_days))
    planned_deleted, planned_details = BotPlannedAction.objects.filter(
        status__in=[
            BotPlannedAction.Status.DONE,
            BotPlannedAction.Status.SKIPPED,
        ],
        finished_at__lt=planned_cutoff,
    ).delete()
    sessions_deleted, sessions_details = BotOnlineSession.objects.filter(
        ends_at__lt=sessions_cutoff,
    ).delete()
    return {
        "planned_deleted": planned_deleted,
        "planned_details": planned_details,
        "sessions_deleted": sessions_deleted,
        "sessions_details": sessions_details,
        "planned_days": planned_days,
        "sessions_days": sessions_days,
    }


def _execute_planned_action(action: BotPlannedAction, now) -> tuple[bool, str, dict]:
    if action.action == BotPlannedAction.Action.PREDICTION:
        strategy_id = action.payload.get("strategy_id")
        try:
            strategy = BotExpertStrategy.objects.select_related("bot__user").get(
                id=strategy_id,
                bot=action.bot,
                bot__is_active=True,
                bot__kind=BotAccount.Kind.EXPERT,
            )
        except BotExpertStrategy.DoesNotExist:
            return False, "strategy_not_found", {}
        created, reason, coupon = _execute_strategy_prediction(strategy, now)
        result = {"coupon": coupon.id} if coupon else {}
        return created, reason, result

    if action.action == BotPlannedAction.Action.READER_ACTIVITY:
        if not action.bot or not action.bot.is_active:
            return False, "bot_not_active", {}
        session_id = action.payload.get("session_id")
        session = None
        if session_id:
            session = BotOnlineSession.objects.filter(
                pk=session_id,
                bot=action.bot,
            ).first()
            if session is None:
                return False, "session_not_found", {}
            if not session.starts_at <= now <= session.ends_at:
                return False, "session_expired", {"session": session.id}
        else:
            session = BotOnlineSession.objects.filter(
                bot=action.bot,
                starts_at__lte=now,
                ends_at__gte=now,
            ).order_by("-starts_at", "-id").first()
            if session is None:
                return False, "no_active_session", {}

        UserPresence.objects.update_or_create(
            user_id=action.bot.user_id,
            defaults={"last_seen_at": now - timedelta(seconds=random.randint(0, 45))},
        )
        if random.random() < 0.58:
            done = _like_prediction(action.bot)
            reason = "like" if done else "like_skipped"
        else:
            done = _follow_or_unfollow(action.bot)
            reason = "follow" if done else "follow_skipped"
        if done and session is not None:
            BotOnlineSession.objects.filter(pk=session.pk).update(
                actions_done=F("actions_done") + 1,
                updated_at=now,
            )
        return done, reason, {"session": session.id} if session else {}

    if action.action == BotPlannedAction.Action.TOURNAMENT_ACTIVITY:
        result = run_bot_tournament_activity(now=now)
        done = bool(result.get("joined") or result.get("created"))
        return done, "tournament_activity" if done else "tournament_skipped", result

    return False, "unknown_action", {}


def plan_bot_reader_activity(now=None, *, max_actions: int = 80) -> dict:
    now = now or timezone.now()
    if not _runtime_feature_enabled("reader_activity"):
        return {"planned": 0, "reason": "bot_runtime_disabled"}
    sessions = list(
        BotOnlineSession.objects.select_related("bot", "bot__user")
        .filter(
            bot__is_active=True,
            starts_at__lte=now,
            ends_at__gt=now,
            actions_planned__lt=F("target_actions"),
        )
        .order_by("starts_at", "id")[:max_actions]
    )
    if not sessions:
        return {"planned": 0, "reason": "no_active_sessions"}

    return _plan_online_session_actions(sessions, now, max_actions=max_actions)


def plan_bot_tournament_activity(now=None) -> dict:
    now = now or timezone.now()
    if not _runtime_feature_enabled("tournaments"):
        return {"planned": 0, "reason": "bot_runtime_disabled"}
    if BotPlannedAction.objects.filter(
        action=BotPlannedAction.Action.TOURNAMENT_ACTIVITY,
        status=BotPlannedAction.Status.PENDING,
    ).exists():
        return {"planned": 0, "skip_reasons": {"already_planned": 1}}
    scheduled_at = now + timedelta(minutes=random.randint(5, 90), seconds=random.randint(0, 59))
    if not _create_planned_action(
        action=BotPlannedAction.Action.TOURNAMENT_ACTIVITY,
        scheduled_at=scheduled_at,
    ):
        return {"planned": 0, "skip_reasons": {"already_planned": 1}}
    return {"planned": 1}


def _create_planned_action(**kwargs) -> bool:
    try:
        BotPlannedAction.objects.create(**kwargs)
    except IntegrityError:
        return False
    return True


def run_bot_activity(max_actions: int = 80, *, execute_immediately: bool = False) -> dict:
    if not execute_immediately:
        return plan_bot_reader_activity(max_actions=max_actions)
    return _run_bot_activity_immediately(max_actions=max_actions)


def _run_bot_activity_immediately(max_actions: int = 80) -> dict:
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


def run_bot_presence_activity(now=None) -> dict:
    now = now or timezone.now()
    if not _runtime_feature_enabled("presence"):
        return {"online": 0, "recent": 0, "bots": 0, "reason": "bot_runtime_disabled"}
    bots = list(
        BotAccount.objects.select_related("user")
        .filter(is_active=True)
        .only("id", "user_id", "kind", "user__id")
    )
    if not bots:
        return {"online": 0, "recent": 0, "bots": 0}

    bot_count = len(bots)
    active_sessions = list(
        BotOnlineSession.objects.select_related("bot", "bot__user")
        .filter(
            bot__is_active=True,
            starts_at__lte=now,
            ends_at__gt=now,
        )
    )
    active_bot_ids = {session.bot_id for session in active_sessions}
    target_online_count = min(
        bot_count,
        max(1, round(bot_count * random.uniform(*BOT_PRESENCE_ONLINE_SHARE_RANGE))),
    )
    sessions_to_start = max(0, target_online_count - len(active_sessions))
    eligible_bots = _eligible_session_start_bots(bots, active_bot_ids, now)
    random.shuffle(eligible_bots)
    created_sessions = [
        _create_online_session(bot, now)
        for bot in eligible_bots[:sessions_to_start]
    ]

    active_sessions.extend(created_sessions)
    active_bot_ids.update(session.bot_id for session in created_sessions)
    inactive_bots = [bot for bot in bots if bot.id not in active_bot_ids]
    random.shuffle(inactive_bots)
    recent_count = min(
        len(inactive_bots),
        round(bot_count * random.uniform(*BOT_PRESENCE_RECENT_SHARE_RANGE)),
    )

    for session in active_sessions:
        UserPresence.objects.update_or_create(
            user_id=session.bot.user_id,
            defaults={"last_seen_at": now - timedelta(seconds=random.randint(0, 240))},
        )

    for bot in inactive_bots[:recent_count]:
        UserPresence.objects.update_or_create(
            user_id=bot.user_id,
            defaults={
                "last_seen_at": now
                - timedelta(minutes=random.randint(*BOT_PRESENCE_RECENT_MINUTES_RANGE))
            },
        )

    action_result = _plan_online_session_actions(
        active_sessions,
        now,
        max_actions=len(active_sessions),
    )

    return {
        "online": len(active_sessions),
        "recent": recent_count,
        "sessions_started": len(created_sessions),
        "session_actions_planned": action_result["planned"],
        "bots": bot_count,
    }


def _eligible_session_start_bots(
    bots: list[BotAccount],
    active_bot_ids: set[int],
    now,
) -> list[BotAccount]:
    recent_cutoff = now - timedelta(minutes=BOT_MIN_MINUTES_BETWEEN_SESSIONS)
    recent_session_bot_ids = set(
        BotOnlineSession.objects.filter(
            ends_at__gte=recent_cutoff,
        ).values_list("bot_id", flat=True)
    )
    return [
        bot
        for bot in bots
        if bot.id not in active_bot_ids and bot.id not in recent_session_bot_ids
    ]


def _create_online_session(bot: BotAccount, now) -> BotOnlineSession:
    duration_minutes = random.randint(*BOT_SESSION_DURATION_MINUTES_RANGE)
    target_actions = random.choices(
        [0, 1, 2],
        weights=BOT_SESSION_TARGET_ACTION_WEIGHTS,
        k=1,
    )[0]
    return BotOnlineSession.objects.create(
        bot=bot,
        starts_at=now,
        ends_at=now + timedelta(minutes=duration_minutes),
        target_actions=target_actions,
    )


def _plan_online_session_actions(
    sessions: list[BotOnlineSession],
    now,
    *,
    max_actions: int,
) -> dict:
    planned = 0
    skipped = 0
    skip_reasons = Counter()
    for session in sessions:
        if planned >= max_actions:
            break
        if session.actions_planned >= session.target_actions:
            skipped += 1
            skip_reasons["session_action_limit"] += 1
            continue
        if BotPlannedAction.objects.filter(
            bot=session.bot,
            action=BotPlannedAction.Action.READER_ACTIVITY,
            status=BotPlannedAction.Status.PENDING,
        ).exists():
            skipped += 1
            skip_reasons["already_planned"] += 1
            continue

        remaining_seconds = int((session.ends_at - now).total_seconds())
        if remaining_seconds <= 60:
            skipped += 1
            skip_reasons["session_finishing"] += 1
            continue
        delay_seconds = random.randint(30, min(remaining_seconds - 1, 20 * 60))
        if _create_planned_action(
            bot=session.bot,
            action=BotPlannedAction.Action.READER_ACTIVITY,
            scheduled_at=now + timedelta(seconds=delay_seconds),
            payload={"session_id": session.id},
        ):
            BotOnlineSession.objects.filter(pk=session.pk).update(
                actions_planned=F("actions_planned") + 1,
                updated_at=now,
            )
            session.actions_planned += 1
            planned += 1
        else:
            skipped += 1
            skip_reasons["already_planned"] += 1

    return {
        "planned": planned,
        "sessions": len(sessions),
        "skipped": skipped,
        "skip_reasons": dict(skip_reasons),
    }


def run_bot_tournament_activity(now=None) -> dict:
    now = now or timezone.now()
    if not _runtime_feature_enabled("tournaments"):
        return {"joined": 0, "created": 0, "skipped": 0, "reason": "bot_runtime_disabled"}
    tournaments = list(
        Tournament.objects.prefetch_related("allowed_sports")
        .filter(
            status=Tournament.Status.PUBLISHED,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .order_by("-is_featured", "ends_at", "id")[:10]
    )
    if not tournaments:
        return {"joined": 0, "created": 0, "skipped": 0, "reason": "no_live_tournaments"}

    joined = 0
    created = 0
    skipped = 0
    skip_reasons = Counter()
    expert_bots = list(
        BotAccount.objects.select_related("user", "expert_strategy").filter(
            kind=BotAccount.Kind.EXPERT,
            is_active=True,
            user__role=User.Role.ANALYST,
        )
    )
    if not expert_bots:
        return {"joined": 0, "created": 0, "skipped": 0, "reason": "no_expert_bots"}

    random.shuffle(tournaments)
    for tournament in tournaments:
        if joined < BOT_TOURNAMENT_MAX_JOINS_PER_RUN:
            joined += _join_tournament_bots(tournament, expert_bots, now)

        if created >= BOT_TOURNAMENT_MAX_COUPONS_PER_RUN:
            continue
        participant = _next_tournament_participant(tournament, now)
        if participant is None:
            skipped += 1
            skip_reasons["no_ready_participant"] += 1
            continue

        strategy = getattr(participant.user, "bot_account", None)
        strategy = getattr(strategy, "expert_strategy", None)
        if strategy is None:
            skipped += 1
            skip_reasons["missing_strategy"] += 1
            continue
        daily_count = _published_bot_coupons_today(strategy, now)
        if daily_count >= strategy.daily_predictions_max:
            skipped += 1
            skip_reasons["daily_limit_reached"] += 1
            continue

        items = _build_tournament_items(tournament, participant, strategy, now)
        if not items:
            skipped += 1
            skip_reasons["no_tournament_pick"] += 1
            continue

        tournament_coupon = _create_tournament_coupon(participant, tournament, items, now)
        if tournament_coupon is None:
            skipped += 1
            skip_reasons["tournament_rule_rejected"] += 1
            continue
        created += 1
        _reschedule_strategy(
            strategy,
            now,
            reached_daily_limit=daily_count + 1 >= strategy.daily_predictions_max,
        )

    return {
        "joined": joined,
        "created": created,
        "skipped": skipped,
        "skip_reasons": dict(skip_reasons),
    }


def preview_bot_tournament_activity(now=None, *, limit: int = 10) -> dict:
    now = now or timezone.now()
    tournaments = list(
        Tournament.objects.prefetch_related("allowed_sports")
        .filter(
            status=Tournament.Status.PUBLISHED,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .order_by("-is_featured", "ends_at", "id")[:10]
    )
    if not tournaments:
        return {
            "tournaments": 0,
            "join_previews": [],
            "coupon_previews": [],
            "skipped": 0,
            "skip_reasons": {"no_live_tournaments": 1},
        }

    expert_bots = list(
        BotAccount.objects.select_related("user", "expert_strategy").filter(
            kind=BotAccount.Kind.EXPERT,
            is_active=True,
            user__role=User.Role.ANALYST,
        )
    )
    if not expert_bots:
        return {
            "tournaments": len(tournaments),
            "join_previews": [],
            "coupon_previews": [],
            "skipped": 0,
            "skip_reasons": {"no_expert_bots": 1},
        }

    join_previews = []
    coupon_previews = []
    skipped = 0
    skip_reasons = Counter()

    for tournament in tournaments:
        if len(join_previews) < limit:
            join_previews.extend(
                _preview_tournament_joins(
                    tournament,
                    expert_bots,
                    now,
                    limit=limit - len(join_previews),
                )
            )

        if len(coupon_previews) >= limit:
            continue
        participants = _ready_tournament_participants(tournament, now)
        if not participants:
            skipped += 1
            skip_reasons["no_ready_participant"] += 1
            continue
        for participant in participants:
            if len(coupon_previews) >= limit:
                break
            strategy = getattr(participant.user.bot_account, "expert_strategy", None)
            if strategy is None:
                skipped += 1
                skip_reasons["missing_strategy"] += 1
                continue
            if _published_bot_coupons_today(strategy, now) >= strategy.daily_predictions_max:
                skipped += 1
                skip_reasons["daily_limit_reached"] += 1
                continue
            items = _build_tournament_items(tournament, participant, strategy, now)
            if not items:
                skipped += 1
                skip_reasons["no_tournament_pick"] += 1
                continue
            validation_error = _tournament_validation_error(tournament, participant, strategy, items)
            if validation_error:
                skipped += 1
                skip_reasons["tournament_rule_rejected"] += 1
                continue
            coupon_previews.append(
                {
                    "tournament": tournament.title,
                    "tournament_id": tournament.id,
                    "bot": participant.user.username,
                    "risk": strategy.risk_profile,
                    "coupon_type": _coupon_type_for_items(items),
                    "confidence": max(
                        _confidence_for_strategy(participant.user.bot_account),
                        tournament.min_confidence or 0,
                    ),
                    "total_coefficient": str(_total_coefficient([pick.coefficient for _, pick in items])),
                    "positions": [_pick_preview(match, pick) for match, pick in items],
                }
            )

    return {
        "tournaments": len(tournaments),
        "join_previews": join_previews[:limit],
        "coupon_previews": coupon_previews[:limit],
        "skipped": skipped,
        "skip_reasons": dict(skip_reasons),
    }


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
            pick = _fallback_pick(match)
            created_at = timezone.now() - timedelta(days=random.randint(1, max(days_back, 1)))
            prediction, was_created = _create_prediction(strategy.bot, match, pick, created_at, settled=True)
            if not was_created:
                continue
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


def _social_handle(username: str) -> str:
    handle = "".join(char if char.isalnum() else "_" for char in username.lower()).strip("_")
    return handle[:28] or "cappers_expert"


def _telegram_account(username: str) -> str:
    return f"https://t.me/{_social_handle(username)}"


def _telegram_channel(username: str) -> str:
    return f"https://t.me/{_social_handle(username)}_tips"


def _published_bot_coupons_today(strategy: BotExpertStrategy, now) -> int:
    return PredictionCoupon.objects.filter(
        author=strategy.bot.user,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        published_at__date=timezone.localdate(now),
    ).count()


def _reschedule_strategy(
    strategy: BotExpertStrategy,
    now,
    *,
    reached_daily_limit: bool = False,
    no_pick: bool = False,
) -> None:
    strategy.last_run_at = now
    if reached_daily_limit:
        next_day = timezone.localdate(now) + timedelta(days=max(strategy.cadence_days, 1))
        base = datetime.combine(next_day, datetime.min.time())
        if timezone.is_naive(base):
            base = timezone.make_aware(base, timezone.get_current_timezone())
        strategy.next_run_at = base + timedelta(
            hours=random.randint(10, 22),
            minutes=random.randint(0, 59),
        )
    elif no_pick:
        strategy.next_run_at = now + timedelta(minutes=random.randint(90, 240))
    else:
        strategy.next_run_at = now + timedelta(
            minutes=random.randint(
                BOT_MIN_MINUTES_BETWEEN_COUPONS,
                BOT_MAX_MINUTES_BETWEEN_COUPONS,
            )
        )
    strategy.save(update_fields=["last_run_at", "next_run_at"])


def _express_probability(strategy: BotExpertStrategy, now=None) -> float:
    if strategy.risk_profile == BotExpertStrategy.RiskProfile.SAFE:
        base_probability = 0.10
        recovery_probability = 0.16
    elif strategy.risk_profile == BotExpertStrategy.RiskProfile.AGGRESSIVE:
        base_probability = 0.20
        recovery_probability = 0.28
    else:
        base_probability = 0.14
        recovery_probability = 0.22

    if now is None:
        return base_probability

    has_recent_express = PredictionCoupon.objects.filter(
        author=strategy.bot.user,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        coupon_type=PredictionCoupon.CouponType.EXPRESS,
        published_at__gte=now - RECENT_EXPRESS_LOOKBACK,
    ).exists()
    if has_recent_express:
        return base_probability
    return recovery_probability


def _join_tournament_bots(tournament: Tournament, expert_bots: list[BotAccount], now) -> int:
    active_user_ids = set(
        TournamentParticipant.objects.filter(
            tournament=tournament,
            status=TournamentParticipant.Status.ACTIVE,
        ).values_list("user_id", flat=True)
    )
    candidates = [bot for bot in expert_bots if bot.user_id not in active_user_ids]
    random.shuffle(candidates)

    joined = 0
    for bot in candidates:
        if joined >= BOT_TOURNAMENT_MAX_JOINS_PER_RUN:
            break
        strategy = getattr(bot, "expert_strategy", None)
        if strategy is None:
            continue
        probability = _tournament_join_probability(strategy, tournament, now)
        if random.random() > probability:
            continue
        try:
            join_tournament(bot.user, tournament)
        except TournamentJoinError:
            continue
        BotActionLog.objects.create(
            bot=bot,
            action=BotActionLog.Action.FOLLOW,
            target=f"Турнир #{tournament.id}",
            meta={"tournament": tournament.id, "kind": "tournament_join"},
        )
        joined += 1
    return joined


def _tournament_join_probability(
    strategy: BotExpertStrategy,
    tournament: Tournament,
    now,
) -> float:
    remaining_hours = (tournament.ends_at - now).total_seconds() / 3600
    if remaining_hours < 2:
        return 0

    probability = BOT_TOURNAMENT_JOIN_PROBABILITY
    allowed_sports = set(tournament.allowed_sports.values_list("code", flat=True))
    focus_sports = set(_strategy_focus_sports(strategy))
    if allowed_sports and allowed_sports.intersection(focus_sports):
        probability += 0.12
    elif allowed_sports:
        probability -= 0.10

    progress = _tournament_progress(tournament, now)
    if tournament.is_featured:
        probability += 0.08
    if strategy.risk_profile == BotExpertStrategy.RiskProfile.SAFE and progress > Decimal("0.65"):
        probability -= 0.08
    if strategy.risk_profile == BotExpertStrategy.RiskProfile.AGGRESSIVE and progress > Decimal("0.55"):
        probability += 0.08
    if remaining_hours > 24:
        probability += 0.04

    return max(0.03, min(probability, 0.45))


def _next_tournament_participant(tournament: Tournament, now) -> TournamentParticipant | None:
    participants = _ready_tournament_participants(tournament, now)
    return random.choice(participants) if participants else None


def _ready_tournament_participants(tournament: Tournament, now) -> list[TournamentParticipant]:
    cutoff_joined_at = now - timedelta(minutes=BOT_TOURNAMENT_MIN_MINUTES_AFTER_JOIN)
    recent_coupon_cutoff = now - timedelta(hours=BOT_TOURNAMENT_MIN_HOURS_BETWEEN_COUPONS)
    return list(
        TournamentParticipant.objects.select_related(
            "user",
            "user__bot_account",
            "user__bot_account__expert_strategy",
        )
        .filter(
            tournament=tournament,
            status=TournamentParticipant.Status.ACTIVE,
            user__bot_account__kind=BotAccount.Kind.EXPERT,
            user__bot_account__is_active=True,
            joined_at__lte=cutoff_joined_at,
        )
        .exclude(tournament_coupons__created_at__gte=recent_coupon_cutoff)
        .order_by("joined_at", "id")[:40]
    )


def _build_tournament_items(
    tournament: Tournament,
    participant: TournamentParticipant,
    strategy: BotExpertStrategy,
    now,
) -> list[tuple[Match, Pick]]:
    used_match_ids = set(
        TournamentPredictionEntry.objects.filter(
            tournament=tournament,
            participant=participant,
        ).values_list("match_id", flat=True)
    )
    taken_picks = _recent_taken_picks(now)

    if tournament.coupon_type_rule == Tournament.CouponTypeRule.EXPRESS:
        items = _build_express_items(strategy, used_match_ids, taken_picks, now, tournament=tournament)
    elif tournament.coupon_type_rule == Tournament.CouponTypeRule.SINGLE:
        items = _build_single_items(strategy, used_match_ids, taken_picks, now, tournament=tournament)
    else:
        items = (
            _build_express_items(strategy, used_match_ids, taken_picks, now, tournament=tournament)
            if random.random() < _express_probability(strategy, now=now)
            else []
        )
        if not items:
            items = _build_single_items(strategy, used_match_ids, taken_picks, now, tournament=tournament)

    items = _filter_tournament_items(tournament, items)
    if not items:
        return []
    if tournament.coupon_type_rule == Tournament.CouponTypeRule.EXPRESS and len(items) < 2:
        return []
    if tournament.coupon_type_rule == Tournament.CouponTypeRule.SINGLE and len(items) != 1:
        return []
    return items


def _filter_tournament_items(
    tournament: Tournament,
    items: list[tuple[Match, Pick]],
) -> list[tuple[Match, Pick]]:
    allowed_sport_ids = set(tournament.allowed_sports.values_list("id", flat=True))
    filtered = []
    for match, pick in items:
        if allowed_sport_ids and match.sport_id not in allowed_sport_ids:
            continue
        if pick.coefficient < Decimal(tournament.min_coefficient or 0):
            continue
        filtered.append((match, pick))
    return filtered


def _create_tournament_coupon(
    participant: TournamentParticipant,
    tournament: Tournament,
    items: list[tuple[Match, Pick]],
    published_at,
) -> TournamentCoupon | None:
    confidence = max(_confidence_for_strategy(participant.user.bot_account), tournament.min_confidence or 0)
    normalized_items = [
        {
            "match": match,
            "market": pick.market,
            "selection": pick.selection,
            "coefficient": pick.coefficient,
        }
        for match, pick in items
    ]
    try:
        validate_tournament_coupon(
            tournament,
            participant,
            confidence=confidence,
            items=normalized_items,
        )
    except TournamentRuleError:
        return None

    try:
        with transaction.atomic():
            locked = TournamentParticipant.objects.select_for_update().get(pk=participant.pk)
            try:
                validate_tournament_coupon(
                    tournament,
                    locked,
                    confidence=confidence,
                    items=normalized_items,
                )
            except TournamentRuleError:
                return None

            coupon, predictions, was_created = _create_coupon(
                locked.user.bot_account,
                items,
                published_at,
            )
            if not was_created:
                return None
            coupon.confidence = confidence
            coupon.save(update_fields=["confidence", "updated_at"])
            tournament_coupon = TournamentCoupon.objects.create(
                tournament=tournament,
                participant=locked,
                coupon=coupon,
            )
            TournamentPredictionEntry.objects.bulk_create(
                [
                    TournamentPredictionEntry(
                        tournament=tournament,
                        participant=locked,
                        tournament_coupon=tournament_coupon,
                        prediction=prediction,
                        match=prediction.match,
                    )
                    for prediction in predictions
                ]
            )
            BotActionLog.objects.create(
                bot=locked.user.bot_account,
                action=BotActionLog.Action.PREDICTION,
                target=f"Турнирный купон #{coupon.id}",
                meta={
                    "tournament": tournament.id,
                    "coupon": coupon.id,
                    "coupon_type": coupon.coupon_type,
                    "positions": len(predictions),
                    "kind": "tournament_prediction",
                },
            )
            return tournament_coupon
    except IntegrityError:
        return None


def _preview_tournament_joins(
    tournament: Tournament,
    expert_bots: list[BotAccount],
    now,
    *,
    limit: int,
) -> list[dict]:
    active_user_ids = set(
        TournamentParticipant.objects.filter(
            tournament=tournament,
            status=TournamentParticipant.Status.ACTIVE,
        ).values_list("user_id", flat=True)
    )
    candidates = []
    for bot in expert_bots:
        if bot.user_id in active_user_ids:
            continue
        strategy = getattr(bot, "expert_strategy", None)
        if strategy is None:
            continue
        probability = _tournament_join_probability(strategy, tournament, now)
        if probability <= 0:
            continue
        candidates.append((probability, bot, strategy))

    candidates = sorted(candidates, key=lambda item: item[0], reverse=True)
    return [
        {
            "tournament": tournament.title,
            "tournament_id": tournament.id,
            "bot": bot.user.username,
            "risk": strategy.risk_profile,
            "join_probability": round(probability, 2),
            "focus_sports": list(_strategy_focus_sports(strategy)),
        }
        for probability, bot, strategy in candidates[:limit]
    ]


def _tournament_validation_error(
    tournament: Tournament,
    participant: TournamentParticipant,
    strategy: BotExpertStrategy,
    items: list[tuple[Match, Pick]],
) -> str:
    confidence = max(_confidence_for_strategy(strategy.bot), tournament.min_confidence or 0)
    normalized_items = [
        {
            "match": match,
            "market": pick.market,
            "selection": pick.selection,
            "coefficient": pick.coefficient,
        }
        for match, pick in items
    ]
    try:
        validate_tournament_coupon(
            tournament,
            participant,
            confidence=confidence,
            items=normalized_items,
        )
    except TournamentRuleError as exc:
        return str(exc)
    return ""


def _build_single_items(
    strategy: BotExpertStrategy,
    used_match_ids: set[int],
    taken_picks: set[tuple[int, str, str]],
    now,
    *,
    tournament: Tournament | None = None,
) -> list[tuple[Match, Pick]]:
    candidate = _choose_scored_candidate(
        _scored_pick_candidates(
            strategy,
            used_match_ids,
            taken_picks,
            now,
            express=False,
            tournament=tournament,
        )
    )
    if candidate is None:
        return []
    used_match_ids.add(candidate[0].id)
    return [candidate]


def _build_express_items(
    strategy: BotExpertStrategy,
    used_match_ids: set[int],
    taken_picks: set[tuple[int, str, str]],
    now,
    *,
    tournament: Tournament | None = None,
) -> list[tuple[Match, Pick]]:
    target_size = random.choice(EXPRESS_SIZE_CHOICES)
    items: list[tuple[Match, Pick]] = []
    local_used_match_ids = set(used_match_ids)
    local_taken_picks = set(taken_picks)
    used_league_ids = set()
    attempts = 0
    max_attempts = target_size * MAX_PICK_ATTEMPTS_MULTIPLIER

    while len(items) < target_size and attempts < max_attempts:
        attempts += 1
        candidate = _choose_scored_candidate(
            _scored_pick_candidates(
                strategy,
                local_used_match_ids,
                local_taken_picks,
                now,
                express=True,
                tournament=tournament,
            ),
            avoid_league_ids=used_league_ids,
        )
        if candidate is None:
            break
        match, pick = candidate
        local_used_match_ids.add(match.id)
        candidate_coefficients = [item.coefficient for _, item in items] + [pick.coefficient]
        total = _total_coefficient(candidate_coefficients)
        if total > EXPRESS_TOTAL_COEFFICIENT_RANGE[1]:
            continue
        items.append((match, pick))
        local_taken_picks.add(_pick_key(match.id, pick.market, pick.selection))
        if match.league_id:
            used_league_ids.add(match.league_id)

    if len(items) < 2:
        return []

    total = _total_coefficient([pick.coefficient for _, pick in items])
    if total < EXPRESS_TOTAL_COEFFICIENT_RANGE[0]:
        return []

    used_match_ids.update(match.id for match, _ in items)
    return items


def _scored_pick_candidates(
    strategy: BotExpertStrategy,
    used_match_ids: set[int],
    taken_picks: set[tuple[int, str, str]],
    now,
    *,
    express: bool = False,
    tournament: Tournament | None = None,
) -> list[tuple[Decimal, Match, Pick]]:
    matches = list(
        _eligible_match_queryset(now, tournament=tournament)
        .exclude(id__in=used_match_ids)
        .order_by("starts_at", "id")[:MAX_MATCH_CHOICES]
    )
    candidates: list[tuple[Decimal, Match, Pick]] = []
    for match in matches:
        picks = _reasonable_picks_for_match(
            match,
            strategy,
            taken_picks,
            express=express,
        )
        for pick in picks:
            candidates.append(
                (
                    _candidate_score(
                        match,
                        pick,
                        strategy,
                        now,
                        express=express,
                        tournament=tournament,
                    ),
                    match,
                    pick,
                )
            )
    return candidates


def _choose_scored_candidate(
    candidates: list[tuple[Decimal, Match, Pick]],
    *,
    avoid_league_ids: set[int] | None = None,
) -> tuple[Match, Pick] | None:
    if not candidates:
        return None

    ranked = sorted(candidates, key=lambda item: item[0], reverse=True)
    if avoid_league_ids:
        diversified = [
            item
            for item in ranked
            if not item[1].league_id or item[1].league_id not in avoid_league_ids
        ]
        if diversified:
            ranked = diversified

    pool = ranked[: min(len(ranked), TOP_SCORED_CANDIDATE_POOL)]
    weights = [max(float(score), 1.0) for score, _, _ in pool]
    _, match, pick = random.choices(pool, weights=weights, k=1)[0]
    return match, pick


def _next_match(
    strategy: BotExpertStrategy,
    used_match_ids: set[int],
    now,
    *,
    tournament: Tournament | None = None,
) -> Match | None:
    queryset = _eligible_match_queryset(now, tournament=tournament).exclude(id__in=used_match_ids)
    if strategy.risk_profile == BotExpertStrategy.RiskProfile.AGGRESSIVE:
        queryset = queryset.filter(
            Q(odds__home_win_bet__gte=Decimal("1.6"))
            | Q(odds__x_bet__gte=Decimal("1.6"))
            | Q(odds__away_win_bet__gte=Decimal("1.6"))
            | Q(odds__goals_over_2_5__gte=Decimal("1.6"))
            | Q(odds__goals_under_2_5__gte=Decimal("1.6"))
        )
        if not queryset.exists():
            queryset = _eligible_match_queryset(now, tournament=tournament).exclude(id__in=used_match_ids)

    count = queryset.count()
    if not count:
        return None
    return queryset[random.randrange(min(count, MAX_MATCH_CHOICES))]


def _eligible_match_queryset(now, *, tournament: Tournament | None = None):
    queryset = (
        Match.objects.select_related("odds", "league", "home_team", "away_team")
        .filter(
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at__gt=now + timedelta(minutes=BOT_MIN_MINUTES_TO_MATCH_START),
        )
        .filter(_has_bot_usable_odds_q())
        .order_by("starts_at", "id")
    )
    if tournament is not None:
        queryset = queryset.filter(starts_at__lte=tournament.ends_at)
        allowed_sport_ids = list(tournament.allowed_sports.values_list("id", flat=True))
        if allowed_sport_ids:
            queryset = queryset.filter(sport_id__in=allowed_sport_ids)
    return queryset


def _pick_for_match(
    match: Match,
    strategy: BotExpertStrategy,
    taken_picks: set[tuple[int, str, str]] | None = None,
    *,
    express: bool = False,
) -> Pick | None:
    options = _reasonable_picks_for_match(
        match,
        strategy,
        taken_picks or set(),
        express=express,
    )
    if not options:
        return None
    market = _choose_market(options)
    source = [pick for pick in options if pick.market == market] or options
    if strategy.risk_profile == BotExpertStrategy.RiskProfile.SAFE:
        source = sorted(source, key=lambda item: abs(item.coefficient - Decimal("1.65")))
        return random.choice(source[: min(len(source), 3)])
    if strategy.risk_profile == BotExpertStrategy.RiskProfile.AGGRESSIVE:
        source = sorted(source, key=lambda item: item.coefficient, reverse=True)
        return random.choice(source[: min(len(source), 4)])
    return random.choice(source)


def _reasonable_picks_for_match(
    match: Match,
    strategy: BotExpertStrategy,
    taken_picks: set[tuple[int, str, str]],
    *,
    express: bool = False,
) -> list[Pick]:
    options = [
        pick
        for pick in _available_picks(match)
        if _pick_is_reasonable(match, pick, strategy, express=express)
    ]
    return [
        pick
        for pick in options
        if _pick_key(match.id, pick.market, pick.selection) not in taken_picks
    ]


def _available_picks(match: Match) -> list[Pick]:
    try:
        odds = match.odds
    except Match.odds.RelatedObjectDoesNotExist:
        return []

    home = match.home_team_name or "Хозяева"
    away = match.away_team_name or "Гости"
    picks = []
    seen = set()

    def add(market: str, selection: str, value) -> None:
        coefficient = _coefficient(value)
        key = (market, selection)
        if coefficient is None or key in seen:
            return
        seen.add(key)
        picks.append(
            Pick(
                market=market,
                selection=selection,
                coefficient=coefficient,
                comment=random.choice(COMMENTS.get(market, COMMENTS["winner"])),
            )
        )

    add("winner", home, odds.home_win_bet)
    add("winner", "Ничья", odds.x_bet)
    add("winner", away, odds.away_win_bet)
    add("total", "ТБ 2.5", odds.goals_over_2_5)
    add("total", "ТМ 2.5", odds.goals_under_2_5)
    add("both_score", "Обе забьют: да", odds.btts_yes)
    add("both_score", "Обе забьют: нет", odds.btts_no)
    add("double_chance", f"{home} или ничья", odds.d_1x)
    add("double_chance", f"Ничья или {away}", odds.d_2x)

    for label, value in _flat_market_items(odds.totals_all):
        add("total", _total_selection(label), value)
    for label, value in _flat_market_items(odds.double_chance_all):
        add("double_chance", _double_chance_selection(label, home, away), value)
    for label, value in _flat_market_items(odds.btts_all):
        add("both_score", _both_score_selection(label), value)
    for label, value in _flat_market_items(odds.handicaps_all):
        selection = _handicap_selection(label, home, away)
        if selection and not _is_zero_handicap_selection(selection):
            add("handicap", selection, value)

    return picks


def _fallback_pick(match: Match) -> Pick:
    home = match.home_team_name or "Хозяева"
    away = match.away_team_name or "Гости"
    market, selection = random.choice(
        [
            ("winner", home),
            ("winner", "Ничья"),
            ("winner", away),
            ("total", random.choice(["ТБ 2.5", "ТМ 2.5", "ТБ 3.5", "ТМ 3.5"])),
            ("both_score", random.choice(["Обе забьют: да", "Обе забьют: нет"])),
            ("double_chance", random.choice([f"{home} или ничья", f"Ничья или {away}", f"{home} или {away}"])),
            ("handicap", random.choice([f"{home} фора -1.5", f"{away} фора +1.5"])),
        ]
    )
    return Pick(
        market=market,
        selection=selection,
        coefficient=Decimal(str(random.choice(["1.55", "1.70", "1.85", "2.05", "2.30"]))),
        comment=random.choice(COMMENTS.get(market, COMMENTS["winner"])),
    )


def _match_title(match: Match) -> str:
    home = match.home_team_name or "Хозяева"
    away = match.away_team_name or "Гости"
    return f"{home} — {away}"


def _pick_preview(match: Match, pick: Pick) -> dict:
    return {
        "match": _match_title(match),
        "starts_at": match.starts_at.isoformat(),
        "sport": match.sport_code,
        "market": pick.market,
        "selection": pick.selection,
        "coefficient": str(pick.coefficient),
    }


def _coupon_type_for_items(items: list[tuple[Match, Pick]]) -> str:
    if len(items) > 1:
        return PredictionCoupon.CouponType.EXPRESS.value
    return PredictionCoupon.CouponType.SINGLE.value


@transaction.atomic
def _create_coupon(
    bot: BotAccount,
    items: list[tuple[Match, Pick]],
    published_at,
    *,
    settled: bool = False,
) -> tuple[PredictionCoupon, list[Prediction], bool]:
    matches = [match for match, _ in items]
    existing = (
        Prediction.objects.filter(coupon__author=bot.user, match__in=matches)
        .select_related("coupon")
        .first()
    )
    if existing is not None:
        return existing.coupon, list(existing.coupon.predictions.all()), False

    stake = Decimal(str(random.choice([100, 150, 200, 250, 300])))
    coefficients = [pick.coefficient for _, pick in items]
    total_coefficient = _total_coefficient(coefficients)
    coupon_type = (
        PredictionCoupon.CouponType.EXPRESS
        if len(items) > 1
        else PredictionCoupon.CouponType.SINGLE
    )
    coupon = PredictionCoupon.objects.create(
        author=bot.user,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        state_status=PredictionCoupon.StateStatus.PENDING,
        coupon_type=coupon_type,
        total_stake=stake,
        possible_payout=(stake * total_coefficient).quantize(Decimal("0.01")),
        confidence=_confidence_for_strategy(bot),
        audience=PredictionCoupon.Audience.FREE,
        published_at=published_at,
    )
    predictions = [
        Prediction(
            coupon=coupon,
            match=match,
            market=pick.market,
            selection=pick.selection,
            coefficient=pick.coefficient,
            stake=stake,
            state_status="" if not settled else Prediction.StateStatus.WIN,
        )
        for match, pick in items
    ]
    predictions = list(Prediction.objects.bulk_create(predictions))
    return coupon, predictions, True


@transaction.atomic
def _create_prediction(
    bot: BotAccount,
    match: Match,
    pick: Pick,
    published_at,
    *,
    settled: bool = False,
) -> tuple[Prediction, bool]:
    _, predictions, was_created = _create_coupon(
        bot,
        [(match, pick)],
        published_at,
        settled=settled,
    )
    return predictions[0], was_created


def _like_prediction(bot: BotAccount) -> bool:
    coupon_ids = list(
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .exclude(author=bot.user)
        .order_by("-created_at")
        .values_list("id", flat=True)[:120]
    )
    if not coupon_ids:
        return False
    coupon_id = random.choice(coupon_ids)
    like, created = PredictionLike.objects.get_or_create(
        user=bot.user,
        prediction_id=coupon_id,
    )
    if not created and random.random() < 0.08:
        like.delete()
        BotActionLog.objects.create(bot=bot, action=BotActionLog.Action.UNLIKE, target=str(coupon_id))
        return True
    if created:
        BotActionLog.objects.create(bot=bot, action=BotActionLog.Action.LIKE, target=str(coupon_id))
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


def _total_coefficient(coefficients) -> Decimal:
    total = Decimal("1")
    for coefficient in coefficients:
        total *= Decimal(str(coefficient))
    return total.quantize(Decimal("0.01"))


def _confidence_for_strategy(bot: BotAccount) -> int:
    try:
        risk_profile = bot.expert_strategy.risk_profile
    except BotExpertStrategy.DoesNotExist:
        risk_profile = BotExpertStrategy.RiskProfile.BALANCED
    if risk_profile == BotExpertStrategy.RiskProfile.SAFE:
        return random.randint(55, 72)
    if risk_profile == BotExpertStrategy.RiskProfile.AGGRESSIVE:
        return random.randint(45, 68)
    return random.randint(50, 75)


def _pick_is_reasonable(
    match: Match,
    pick: Pick,
    strategy: BotExpertStrategy,
    *,
    express: bool = False,
) -> bool:
    minimum, maximum = (
        EXPRESS_LEG_COEFFICIENT_RANGE
        if express
        else SINGLE_COEFFICIENT_RANGES.get(
            strategy.risk_profile,
            SINGLE_COEFFICIENT_RANGES[BotExpertStrategy.RiskProfile.BALANCED],
        )
    )
    if not minimum <= pick.coefficient <= maximum:
        return False
    if pick.market == "total" and not _total_line_reasonable(match, pick.selection):
        return False
    if pick.market == "handicap" and _is_zero_handicap_selection(pick.selection):
        return False
    return True


def _candidate_score(
    match: Match,
    pick: Pick,
    strategy: BotExpertStrategy,
    now,
    *,
    express: bool = False,
    tournament: Tournament | None = None,
) -> Decimal:
    score = Decimal("100")
    target = _target_coefficient(strategy, express=express, tournament=tournament, now=now)
    score -= abs(pick.coefficient - target) * Decimal("28")

    market_weight = Decimal(MARKET_WEIGHTS.get(pick.market, 5))
    score += market_weight / Decimal("3")

    hours_to_start = Decimal(
        str(max(0, (match.starts_at - now).total_seconds() / 3600))
    )
    if hours_to_start <= Decimal("6"):
        score += Decimal("18")
    elif hours_to_start <= Decimal("24"):
        score += Decimal("15")
    elif hours_to_start <= Decimal("72"):
        score += Decimal("8")
    else:
        score -= Decimal("8")

    focus_sports = _strategy_focus_sports(strategy)
    if match.sport_code in focus_sports:
        score += Decimal("10")

    if match.league_id:
        score += Decimal("4")
    league_name = (match.league_name or match.league_name_en or "").lower()
    if any(marker in league_name for marker in ("premier", "league", "liga", "serie", "bundes")):
        score += Decimal("5")

    selection = (pick.selection or "").lower()
    if strategy.risk_profile == BotExpertStrategy.RiskProfile.SAFE:
        if pick.market == "double_chance":
            score += Decimal("6")
        if "ничья" == selection.strip():
            score -= Decimal("14")
    elif strategy.risk_profile == BotExpertStrategy.RiskProfile.AGGRESSIVE:
        if pick.market in {"winner", "handicap", "total"}:
            score += Decimal("5")
        if "ничья" == selection.strip():
            score += Decimal("4")

    if tournament is not None:
        progress = _tournament_progress(tournament, now)
        if progress >= Decimal("0.75") and strategy.risk_profile == BotExpertStrategy.RiskProfile.AGGRESSIVE:
            score += min(pick.coefficient, Decimal("3.50")) * Decimal("4")
        elif progress <= Decimal("0.25") and strategy.risk_profile == BotExpertStrategy.RiskProfile.SAFE:
            score -= max(Decimal("0"), pick.coefficient - Decimal("1.85")) * Decimal("10")

    if express:
        if pick.market == "double_chance":
            score += Decimal("4")
        if pick.coefficient > Decimal("2.15"):
            score -= Decimal("10")

    return max(score.quantize(Decimal("0.01")), Decimal("1.00"))


def _target_coefficient(
    strategy: BotExpertStrategy,
    *,
    express: bool = False,
    tournament: Tournament | None = None,
    now=None,
) -> Decimal:
    if express:
        targets = {
            BotExpertStrategy.RiskProfile.SAFE: Decimal("1.45"),
            BotExpertStrategy.RiskProfile.BALANCED: Decimal("1.65"),
            BotExpertStrategy.RiskProfile.AGGRESSIVE: Decimal("1.90"),
        }
    else:
        targets = {
            BotExpertStrategy.RiskProfile.SAFE: Decimal("1.62"),
            BotExpertStrategy.RiskProfile.BALANCED: Decimal("1.90"),
            BotExpertStrategy.RiskProfile.AGGRESSIVE: Decimal("2.45"),
        }
    target = targets.get(strategy.risk_profile, targets[BotExpertStrategy.RiskProfile.BALANCED])

    if tournament is not None and now is not None:
        progress = _tournament_progress(tournament, now)
        if progress >= Decimal("0.75") and strategy.risk_profile == BotExpertStrategy.RiskProfile.AGGRESSIVE:
            target += Decimal("0.35")
        elif progress <= Decimal("0.25") and strategy.risk_profile == BotExpertStrategy.RiskProfile.SAFE:
            target -= Decimal("0.10")

    return target


def _tournament_progress(tournament: Tournament, now) -> Decimal:
    total_seconds = (tournament.ends_at - tournament.starts_at).total_seconds()
    if total_seconds <= 0:
        return Decimal("1")
    elapsed_seconds = max(0, (now - tournament.starts_at).total_seconds())
    progress = Decimal(str(elapsed_seconds / total_seconds))
    return max(Decimal("0"), min(progress, Decimal("1")))


def _strategy_focus_sports(strategy: BotExpertStrategy) -> tuple[str, ...]:
    bot_id = getattr(strategy, "bot_id", None)
    if bot_id is None:
        bot_id = getattr(getattr(strategy, "bot", None), "id", 0) or 0
    return BOT_SPORT_FOCUS_ROTATION[bot_id % len(BOT_SPORT_FOCUS_ROTATION)]


def _total_line_reasonable(match: Match, selection: str) -> bool:
    line = _line_from_label(selection)
    if line is None:
        return False
    value = Decimal(line)
    sport_code = getattr(match, "sport_code", "football")
    if sport_code == "football":
        return Decimal("0.5") <= value <= Decimal("4.5")
    if sport_code == "hockey":
        return Decimal("3.5") <= value <= Decimal("7.5")
    if sport_code == "basketball":
        return Decimal("120.5") <= value <= Decimal("240.5")
    if sport_code == "tennis":
        return Decimal("12.5") <= value <= Decimal("45.5")
    return Decimal("0.5") <= value <= Decimal("8.5")


def _has_bot_usable_odds_q() -> Q:
    direct = (
        Q(odds__home_win_bet__isnull=False)
        | Q(odds__x_bet__isnull=False)
        | Q(odds__away_win_bet__isnull=False)
        | Q(odds__goals_over_2_5__isnull=False)
        | Q(odds__goals_under_2_5__isnull=False)
        | Q(odds__btts_yes__isnull=False)
        | Q(odds__btts_no__isnull=False)
        | Q(odds__d_1x__isnull=False)
        | Q(odds__d_2x__isnull=False)
    )
    grouped = (
        ~Q(odds__totals_all={})
        | ~Q(odds__double_chance_all={})
        | ~Q(odds__btts_all={})
        | ~Q(odds__handicaps_all={})
    )
    return direct | grouped


def _recent_taken_picks(now) -> set[tuple[int, str, str]]:
    since = now - RECENT_PREDICTION_LOOKBACK
    return {
        _pick_key(match_id, market, selection)
        for match_id, market, selection in Prediction.objects.filter(
            coupon__author__bot_account__kind=BotAccount.Kind.EXPERT,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            match__sync_scope=Match.SyncScope.PREMATCH,
            match__starts_at__gt=now,
            created_at__gte=since,
        ).values_list("match_id", "market", "selection")
    }


def _pick_key(match_id: int, market: str, selection: str) -> tuple[int, str, str]:
    return (match_id, str(market or "").strip().lower(), str(selection or "").strip().lower())


def _choose_market(options: list[Pick]) -> str:
    markets = sorted({pick.market for pick in options})
    weights = [MARKET_WEIGHTS.get(market, 5) for market in markets]
    return random.choices(markets, weights=weights, k=1)[0]


def _flat_market_items(payload) -> list[tuple[str, object]]:
    if not isinstance(payload, dict):
        return []

    items = []
    for key, value in payload.items():
        coefficient = _coefficient(value)
        if coefficient is not None:
            items.append((str(key), coefficient))
        elif isinstance(value, dict):
            for nested_key, nested_value in value.items():
                nested_coefficient = _coefficient(nested_value)
                if nested_coefficient is not None:
                    items.append((f"{key} {nested_key}", nested_coefficient))
    return items


def _total_selection(label: str) -> str:
    line = _line_from_label(label) or "2.5"
    normalized = _normalize_label(label)
    if "under" in normalized or "меньше" in normalized:
        return f"ТМ {line}"
    return f"ТБ {line}"


def _double_chance_selection(label: str, home: str, away: str) -> str:
    normalized = _normalize_label(label).replace(" ", "")
    if normalized in {"1x", "homeordraw", "хозяеваилиничья"}:
        return f"{home} или ничья"
    if normalized in {"x2", "draworaway", "ничьяилигости", "2x"}:
        return f"Ничья или {away}"
    if normalized in {"12", "homeoraway", "хозяеваилигости"}:
        return f"{home} или {away}"
    if "2" in normalized and "x" in normalized:
        return f"Ничья или {away}"
    if "1" in normalized and "x" in normalized:
        return f"{home} или ничья"
    return f"{home} или {away}"


def _both_score_selection(label: str) -> str:
    normalized = _normalize_label(label)
    if any(marker in normalized for marker in ("no", "нет")):
        return "Обе забьют: нет"
    return "Обе забьют: да"


def _handicap_selection(label: str, home: str, away: str) -> str:
    line = _line_from_label(label)
    if line is None:
        return ""
    normalized = _normalize_label(label)
    if any(marker in normalized for marker in ("away", "гости", "team 2", "команда 2", " 2 ")):
        return f"{away} фора {line}"
    return f"{home} фора {line}"


def _is_zero_handicap_selection(selection: str) -> bool:
    line = _line_from_label(selection)
    return line in {"0", "+0", "-0", "0.0", "+0.0", "-0.0"}


def _line_from_label(label: str) -> str | None:
    matches = re.findall(r"[-+]?\d+(?:[.,]\d+)?", str(label or ""))
    if not matches:
        return None
    return matches[-1].replace(",", ".")


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", str(label or "").strip().lower())


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
