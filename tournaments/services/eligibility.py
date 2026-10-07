from dataclasses import asdict, dataclass
from datetime import timedelta

from django.utils import timezone

from cabinet.models import AnalystFollow
from front.models import PredictionLike
from game.models import Match, Prediction, PredictionCoupon
from tournaments.models import Tournament, TournamentEligibilityRule, TournamentResult
from wallets.models import CoinWallet


NEW_USER_DAYS = 30


@dataclass(frozen=True)
class EligibilityRuleResult:
    code: str
    title: str
    required: int | bool | str
    current: int | bool | str
    passed: bool
    description: str = ""
    reason: str = ""


def check_tournament_eligibility(user, tournament: Tournament) -> dict:
    authenticated = bool(getattr(user, "is_authenticated", False))
    hard_rules = []
    condition_rules = []

    if not authenticated:
        hard_rules.append(
            EligibilityRuleResult(
                code="auth",
                title="Авторизация",
                required=True,
                current=False,
                passed=False,
                reason="Войдите, чтобы участвовать в турнире.",
            )
        )
        return _eligibility_response(user, tournament, hard_rules, condition_rules)

    # Money prizes are paid to the real balance, which only analysts have.
    money_prizes = not tournament.analysts_only and tournament.has_money_prizes()
    if tournament.analysts_only or money_prizes:
        hard_rules.append(
            EligibilityRuleResult(
                code="analysts_only",
                title="Статус каппера",
                required=True,
                current=bool(getattr(user, "is_analyst", False)),
                passed=bool(getattr(user, "is_analyst", False)),
                reason=(
                    "В турнирах с денежными призами участвуют только капперы."
                    if money_prizes
                    else "Участвовать могут только капперы."
                ),
            )
        )

    if tournament.vip_only:
        is_vip = bool(getattr(user, "is_vip", False))
        hard_rules.append(
            EligibilityRuleResult(
                code="vip_only",
                title="VIP-статус",
                required=True,
                current=is_vip,
                passed=is_vip,
                reason="Нужен активный VIP-статус.",
            )
        )

    if tournament.new_users_only:
        is_new = _is_new_user(user)
        hard_rules.append(
            EligibilityRuleResult(
                code="new_users_only",
                title="Новый пользователь",
                required=True,
                current=is_new,
                passed=is_new,
                reason="Турнир доступен только новым пользователям.",
            )
        )

    if tournament.entry_type == Tournament.EntryType.PAID:
        balance = _coin_balance(user)
        required_coins = int(tournament.entry_fee_coins or 0)
        hard_rules.append(
            EligibilityRuleResult(
                code="entry_fee_coins",
                title="Коины для участия",
                required=required_coins,
                current=balance,
                passed=balance >= required_coins,
                reason="Недостаточно средств на виртуальном счете.",
            )
        )

    condition_rules.extend(_legacy_activity_rules(user, tournament))
    condition_rules.extend(_configured_rules(user, tournament))

    return _eligibility_response(user, tournament, hard_rules, condition_rules)


def _eligibility_response(
    user,
    tournament: Tournament,
    hard_rules: list[EligibilityRuleResult],
    condition_rules: list[EligibilityRuleResult],
) -> dict:
    hard_allowed = all(rule.passed for rule in hard_rules)
    if tournament.eligibility_mode == Tournament.EligibilityMode.ANY and condition_rules:
        conditions_allowed = any(rule.passed for rule in condition_rules)
    else:
        conditions_allowed = all(rule.passed for rule in condition_rules)

    active_rules = [*hard_rules, *condition_rules]
    failed_rules = [rule for rule in active_rules if not rule.passed]
    return {
        "allowed": hard_allowed and conditions_allowed,
        "hard_allowed": hard_allowed,
        "conditions_allowed": conditions_allowed,
        "mode": tournament.eligibility_mode,
        "entry_fee_coins": int(tournament.entry_fee_coins or 0),
        "coin_balance": _coin_balance(user) if getattr(user, "is_authenticated", False) else 0,
        "has_enough_coins": (
            tournament.entry_type != Tournament.EntryType.PAID
            or (
                getattr(user, "is_authenticated", False)
                and _coin_balance(user) >= int(tournament.entry_fee_coins or 0)
            )
        ),
        "hard_rules": [asdict(rule) for rule in hard_rules],
        "condition_rules": [asdict(rule) for rule in condition_rules],
        "rules": [asdict(rule) for rule in active_rules],
        "reasons": [_rule_reason(rule) for rule in failed_rules],
    }


def _legacy_activity_rules(user, tournament: Tournament) -> list[EligibilityRuleResult]:
    rules = []
    sport = tournament.eligibility_sport
    sport_label = _sport_label(sport)

    required_predictions = int(tournament.min_user_predictions or 0)
    if required_predictions > 0:
        current = _published_prediction_coupons_count(user, sport=sport)
        rules.append(
            EligibilityRuleResult(
                code="min_user_predictions",
                title=f"Опубликованные прогнозы{sport_label}",
                required=required_predictions,
                current=current,
                passed=current >= required_predictions,
                reason=f"Нужно минимум {required_predictions} опубликованных прогнозов{sport_label}.",
            )
        )

    required_wins = int(tournament.min_user_wins or 0)
    if required_wins > 0:
        current = _winning_predictions_count(user, sport=sport)
        rules.append(
            EligibilityRuleResult(
                code="min_user_wins",
                title=f"Выигранные прогнозы{sport_label}",
                required=required_wins,
                current=current,
                passed=current >= required_wins,
                reason=f"Нужно минимум {required_wins} выигранных прогнозов{sport_label}.",
            )
        )

    return rules


def _configured_rules(user, tournament: Tournament) -> list[EligibilityRuleResult]:
    queryset = tournament.eligibility_rules.filter(is_active=True).select_related("sport").order_by("sort_order", "id")
    return [_evaluate_configured_rule(user, rule) for rule in queryset]


def _evaluate_configured_rule(user, rule: TournamentEligibilityRule) -> EligibilityRuleResult:
    current = _metric_value(user, rule)
    required = _required_value(rule)
    passed = _compare(current, required, rule.operator)
    title = rule.title or _rule_default_title(rule)
    return EligibilityRuleResult(
        code=rule.rule_type,
        title=title,
        required=required,
        current=current,
        passed=passed,
        description=rule.description,
        reason=_configured_rule_reason(title, current, required, rule.operator),
    )


def _metric_value(user, rule: TournamentEligibilityRule) -> int:
    if rule.rule_type == TournamentEligibilityRule.RuleType.VIP_STATUS:
        return int(bool(getattr(user, "is_vip", False)))
    if rule.rule_type == TournamentEligibilityRule.RuleType.NEW_USER:
        days = int(rule.value or NEW_USER_DAYS)
        return int(_is_new_user(user, days=days))
    if rule.rule_type == TournamentEligibilityRule.RuleType.TOURNAMENT_WINS:
        return TournamentResult.objects.filter(participant__user=user, rank=1).count()
    if rule.rule_type == TournamentEligibilityRule.RuleType.PREDICTIONS_COUNT:
        return _published_prediction_coupons_count(user, sport=rule.sport)
    if rule.rule_type == TournamentEligibilityRule.RuleType.WINNING_PREDICTIONS_COUNT:
        return _winning_predictions_count(user, sport=rule.sport)
    if rule.rule_type == TournamentEligibilityRule.RuleType.FOLLOWERS_COUNT:
        return AnalystFollow.objects.filter(analyst=user).count()
    if rule.rule_type == TournamentEligibilityRule.RuleType.LIKES_COUNT:
        return PredictionLike.objects.filter(prediction__author=user).count()
    if rule.rule_type == TournamentEligibilityRule.RuleType.LIVE_PREDICTIONS_COUNT:
        return _live_predictions_count(user, sport=rule.sport)
    return 0


def _required_value(rule: TournamentEligibilityRule) -> int:
    if rule.rule_type in (
        TournamentEligibilityRule.RuleType.VIP_STATUS,
        TournamentEligibilityRule.RuleType.NEW_USER,
    ):
        return 1
    return int(rule.value or 0)


def _compare(current: int, required: int, operator: str) -> bool:
    if operator == TournamentEligibilityRule.Operator.LTE:
        return current <= required
    if operator == TournamentEligibilityRule.Operator.EQ:
        return current == required
    return current >= required


def _published_prediction_coupons_count(user, *, sport=None) -> int:
    queryset = PredictionCoupon.objects.filter(
        author=user,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    if sport:
        queryset = queryset.filter(predictions__match__sport=sport).distinct()
    return queryset.count()


def _winning_predictions_count(user, *, sport=None) -> int:
    queryset = Prediction.objects.filter(
        coupon__author=user,
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        state_status=Prediction.StateStatus.WIN,
    )
    if sport:
        queryset = queryset.filter(match__sport=sport)
    return queryset.count()


def _live_predictions_count(user, *, sport=None) -> int:
    queryset = Prediction.objects.filter(
        coupon__author=user,
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        match__sync_scope=Match.SyncScope.LIVE,
    )
    if sport:
        queryset = queryset.filter(match__sport=sport)
    return queryset.count()


def _is_new_user(user, *, days: int = NEW_USER_DAYS) -> bool:
    date_joined = getattr(user, "date_joined", None)
    if not date_joined:
        return False
    return date_joined >= timezone.now() - timedelta(days=max(days, 1))


def _coin_balance(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    return int(CoinWallet.objects.filter(user=user).values_list("balance", flat=True).first() or 0)


def _sport_label(sport) -> str:
    if not sport:
        return ""
    return f" по спорту «{sport.name_ru or sport.name}»"


def _rule_default_title(rule: TournamentEligibilityRule) -> str:
    title = rule.get_rule_type_display()
    if rule.sport_id:
        title = f"{title} ({rule.sport.name_ru or rule.sport.name})"
    return title


def _configured_rule_reason(title: str, current: int, required: int, operator: str) -> str:
    if operator == TournamentEligibilityRule.Operator.LTE:
        return f"{title}: нужно не больше {required}, сейчас {current}."
    if operator == TournamentEligibilityRule.Operator.EQ:
        return f"{title}: нужно {required}, сейчас {current}."
    missing = max(required - current, 0)
    if missing:
        return f"{title}: не хватает {missing}."
    return f"{title}: условие не выполнено."


def _rule_reason(rule: EligibilityRuleResult) -> str:
    if rule.reason:
        return rule.reason
    return f"{rule.title}: условие не выполнено."
