from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from django.db import migrations
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum


MIGRATION_COIN_PRICE_RUB = Decimal("5.00")
COIN_QUANT = Decimal("1")
OLD_MIGRATION_MARKER_NOTE = "Миграция: стартовые коины уже учтены в перенесенном балансе"
NEW_MIGRATION_MARKER_NOTE = "Миграция legacy RUB: баланс пересчитан по курсу 5.00 ₽/coin"

LEGACY_DEBIT_KINDS = {
    "prediction_stake",
    "copybet_stake",
}
LEGACY_REFUND_KINDS = {
    "prediction_refund",
    "copybet_refund",
}
SETTLED_COUPON_STATES = {"win", "lose", "refund"}


def _decimal(value):
    return Decimal(str(value or 0))


def _rub_balance_to_coins(value):
    amount = _decimal(value)
    if amount < 0:
        raise RuntimeError(f"Negative legacy balance cannot be migrated: {amount}")
    return int(
        (amount / MIGRATION_COIN_PRICE_RUB).quantize(
            COIN_QUANT,
            rounding=ROUND_FLOOR,
        )
    )


def _rub_debit_to_coins(value):
    amount = abs(_decimal(value))
    return int(
        (amount / MIGRATION_COIN_PRICE_RUB).quantize(
            COIN_QUANT,
            rounding=ROUND_CEILING,
        )
    )


def _rub_credit_to_coins(value):
    amount = abs(_decimal(value))
    return int(
        (amount / MIGRATION_COIN_PRICE_RUB).quantize(
            COIN_QUANT,
            rounding=ROUND_FLOOR,
        )
    )


def _legacy_transaction_amount_to_coins(value, kind):
    amount = _decimal(value)
    if amount == 0:
        return 0
    if kind in LEGACY_DEBIT_KINDS:
        return -_rub_debit_to_coins(amount)
    if kind in LEGACY_REFUND_KINDS:
        return _rub_debit_to_coins(amount)
    if amount < 0:
        return -_rub_debit_to_coins(amount)
    return _rub_credit_to_coins(amount)


def _round_coin_payout(stake_coins, coefficient):
    stake = _decimal(stake_coins)
    coefficient = _decimal(coefficient)
    if stake <= 0 or coefficient <= 0:
        return 0
    return int(
        (stake * coefficient).quantize(
            COIN_QUANT,
            rounding=ROUND_HALF_UP,
        )
    )


def _legacy_note(kind, note):
    text = f"Legacy RUB ({kind}) @ 5.00 ₽/coin. {note or ''}".strip()
    return text[:255]


def _migration_applied_at(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT applied
            FROM django_migrations
            WHERE app = %s AND name = %s
            ORDER BY applied DESC
            LIMIT 1
            """,
            ["wallets", "0008_migrate_virtual_balance_to_coins"],
        )
        row = cursor.fetchone()
    return row[0] if row else None


def _coupon_coefficient(Prediction, coupon):
    old_stake = _decimal(coupon.total_stake)
    old_payout = _decimal(coupon.possible_payout)
    if old_stake > 0 and old_payout > 0:
        return old_payout / old_stake

    coefficient = Decimal("1")
    found = False
    for value in Prediction.objects.filter(coupon_id=coupon.pk).values_list(
        "coefficient",
        flat=True,
    ):
        numeric = _decimal(value)
        if numeric <= 0:
            continue
        coefficient *= numeric
        found = True
    return coefficient if found else Decimal("0")


def _convert_legacy_coupons(apps, cutover_at):
    PredictionCoupon = apps.get_model("game", "PredictionCoupon")
    Prediction = apps.get_model("game", "Prediction")

    coupon_ids = []
    coupons = PredictionCoupon.objects.filter(created_at__lte=cutover_at).order_by("id")
    for coupon in coupons.iterator():
        old_stake = _decimal(coupon.total_stake)
        if old_stake <= 0:
            continue

        coefficient = _coupon_coefficient(Prediction, coupon)
        stake_coins = _rub_debit_to_coins(old_stake)
        payout_coins = _round_coin_payout(stake_coins, coefficient)

        PredictionCoupon.objects.filter(pk=coupon.pk).update(
            total_stake=Decimal(stake_coins),
            possible_payout=Decimal(payout_coins),
        )
        Prediction.objects.filter(coupon_id=coupon.pk).update(
            stake=Decimal(stake_coins),
        )
        coupon_ids.append(coupon.pk)

    return set(coupon_ids)


def _copybet_coefficient(bet):
    old_stake = _decimal(bet.stake)
    old_payout = _decimal(bet.possible_payout)
    if old_stake <= 0 or old_payout <= 0:
        return Decimal("0")
    return old_payout / old_stake


def _convert_legacy_copied_bets(apps, cutover_at):
    CopiedBet = apps.get_model("wallets", "CopiedBet")

    converted_ids = set()
    queryset = CopiedBet.objects.filter(created_at__lte=cutover_at).order_by("id")
    for bet in queryset.iterator():
        old_stake = _decimal(bet.stake)
        if old_stake <= 0:
            continue

        stake_coins = _rub_debit_to_coins(old_stake)
        payout_coins = _round_coin_payout(stake_coins, _copybet_coefficient(bet))

        if bet.state_status == "win":
            profit = Decimal(payout_coins - stake_coins)
        elif bet.state_status == "lose":
            profit = Decimal(-stake_coins)
        else:
            profit = Decimal("0")

        CopiedBet.objects.filter(pk=bet.pk).update(
            stake=Decimal(stake_coins),
            possible_payout=Decimal(payout_coins),
            profit=profit,
        )
        converted_ids.add(bet.pk)

    return converted_ids


def _convert_copybetting_settings_and_totals(apps, cutover_at):
    CopyBettingSubscription = apps.get_model("wallets", "CopyBettingSubscription")
    CopiedBet = apps.get_model("wallets", "CopiedBet")

    subscriptions = CopyBettingSubscription.objects.order_by("id")
    for subscription in subscriptions.iterator():
        updates = {}

        # Settings edited after cutover are already coin-native and must not be divided.
        if subscription.updated_at <= cutover_at:
            updates["bank_amount"] = Decimal(
                _rub_debit_to_coins(subscription.bank_amount)
            )
            updates["stop_loss_amount"] = Decimal(
                _rub_debit_to_coins(subscription.stop_loss_amount)
                if _decimal(subscription.stop_loss_amount) > 0
                else 0
            )
            updates["max_single_stake"] = Decimal(
                _rub_debit_to_coins(subscription.max_single_stake)
                if _decimal(subscription.max_single_stake) > 0
                else 0
            )

        bets = list(
            CopiedBet.objects.filter(subscription_id=subscription.pk)
            .order_by("settled_at", "created_at", "id")
            .values(
                "stake",
                "profit",
                "state_status",
            )
        )
        if bets:
            total_staked = sum((_decimal(row["stake"]) for row in bets), Decimal("0"))
            total_profit = sum((_decimal(row["profit"]) for row in bets), Decimal("0"))
            current_loss = Decimal("0")
            for row in bets:
                profit = _decimal(row["profit"])
                if profit < 0:
                    current_loss += abs(profit)
                elif profit > 0:
                    current_loss = max(Decimal("0"), current_loss - profit)
            updates["total_staked"] = total_staked
            updates["total_profit"] = total_profit
            updates["current_loss"] = current_loss
        elif subscription.updated_at <= cutover_at:
            updates["total_staked"] = Decimal(
                _rub_credit_to_coins(subscription.total_staked)
            )
            raw_profit = _decimal(subscription.total_profit)
            updates["total_profit"] = Decimal(
                -_rub_debit_to_coins(raw_profit)
                if raw_profit < 0
                else _rub_credit_to_coins(raw_profit)
            )
            updates["current_loss"] = Decimal(
                _rub_debit_to_coins(subscription.current_loss)
                if _decimal(subscription.current_loss) > 0
                else 0
            )

        if updates:
            CopyBettingSubscription.objects.filter(pk=subscription.pk).update(
                **updates
            )


def _rebuild_capper_bank_stats(apps):
    PredictionCoupon = apps.get_model("game", "PredictionCoupon")
    CapperBankStats = apps.get_model("wallets", "CapperBankStats")

    user_ids = set(
        PredictionCoupon.objects.filter(published_status="published").values_list(
            "author_id",
            flat=True,
        )
    )
    user_ids.update(CapperBankStats.objects.values_list("user_id", flat=True))

    for user_id in user_ids:
        published = PredictionCoupon.objects.filter(
            author_id=user_id,
            published_status="published",
        )
        win_profit = ExpressionWrapper(
            F("possible_payout") - F("total_stake"),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
        values = published.aggregate(
            coupons_count=Count("id"),
            stake_sum=Sum("total_stake"),
            average_stake=Avg("total_stake"),
            lost_amount=Sum(
                "total_stake",
                filter=Q(state_status="lose"),
            ),
            earned_amount=Sum(
                win_profit,
                filter=Q(state_status="win"),
            ),
            pending_stake=Sum(
                "total_stake",
                filter=Q(state_status="pending"),
            ),
            settled_count=Count(
                "id",
                filter=Q(state_status__in=SETTLED_COUPON_STATES),
            ),
        )
        total_stake = values["stake_sum"] or Decimal("0")
        average_stake = values["average_stake"] or Decimal("0")
        lost_amount = values["lost_amount"] or Decimal("0")
        earned_amount = values["earned_amount"] or Decimal("0")
        pending_stake = values["pending_stake"] or Decimal("0")

        CapperBankStats.objects.update_or_create(
            user_id=user_id,
            defaults={
                "coupons_count": values["coupons_count"] or 0,
                "settled_count": values["settled_count"] or 0,
                "total_stake": total_stake,
                "average_stake": average_stake,
                "lost_amount": lost_amount,
                "earned_amount": earned_amount,
                "pending_stake": pending_stake,
                "net_result": earned_amount - lost_amount,
            },
        )


def _rebuild_tournament_coin_results(apps):
    TournamentResult = apps.get_model("tournaments", "TournamentResult")
    TournamentCoupon = apps.get_model("tournaments", "TournamentCoupon")

    for result in TournamentResult.objects.order_by("id").iterator():
        coupons = list(
            TournamentCoupon.objects.filter(
                tournament_id=result.tournament_id,
                participant_id=result.participant_id,
            )
            .values(
                "coupon__total_stake",
                "coupon__possible_payout",
                "coupon__state_status",
            )
        )
        total_stake = sum(
            (_decimal(row["coupon__total_stake"]) for row in coupons),
            Decimal("0"),
        )
        profit = Decimal("0")
        wins = losses = refunds = pending = 0
        for row in coupons:
            state = row["coupon__state_status"]
            stake = _decimal(row["coupon__total_stake"])
            payout = _decimal(row["coupon__possible_payout"])
            if state == "win":
                wins += 1
                profit += payout - stake
            elif state == "lose":
                losses += 1
                profit -= stake
            elif state == "refund":
                refunds += 1
            else:
                pending += 1

        roi = (
            (profit / total_stake * Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            if total_stake > 0
            else Decimal("0")
        )
        TournamentResult.objects.filter(pk=result.pk).update(
            coupons_count=len(coupons),
            wins_count=wins,
            losses_count=losses,
            refunds_count=refunds,
            pending_count=pending,
            total_stake=total_stake,
            profit=profit,
            roi_percent=roi,
            # prize_amount intentionally remains RUB and is never converted.
        )


def _related_coin_amount(apps, transaction):
    kind = transaction.kind
    related_model = transaction.related_model
    related_id = transaction.related_id

    if related_id and related_model == "game.predictioncoupon":
        PredictionCoupon = apps.get_model("game", "PredictionCoupon")
        coupon = PredictionCoupon.objects.filter(pk=related_id).first()
        if coupon:
            if kind == "prediction_stake":
                return -int(_decimal(coupon.total_stake))
            if kind == "prediction_payout":
                return int(_decimal(coupon.possible_payout))
            if kind == "prediction_refund":
                return int(_decimal(coupon.total_stake))

    if related_id and related_model == "wallets.copiedbet":
        CopiedBet = apps.get_model("wallets", "CopiedBet")
        bet = CopiedBet.objects.filter(pk=related_id).first()
        if bet:
            if kind == "copybet_stake":
                return -int(_decimal(bet.stake))
            if kind == "copybet_payout":
                return int(_decimal(bet.possible_payout))
            if kind == "copybet_refund":
                return int(_decimal(bet.stake))

    return _legacy_transaction_amount_to_coins(transaction.amount, kind)


def _corrected_wallet_balance(current_balance, old_legacy_balance):
    corrected_legacy_balance = _rub_balance_to_coins(old_legacy_balance)
    return max(
        0,
        int(current_balance) - int(old_legacy_balance) + corrected_legacy_balance,
    )


def _repair_already_migrated_wallets_and_ledger(apps, cutover_at):
    CoinWallet = apps.get_model("wallets", "CoinWallet")
    CoinTransaction = apps.get_model("wallets", "CoinTransaction")

    markers = list(
        CoinTransaction.objects.filter(
            kind="initial_grant",
            amount=0,
            note=OLD_MIGRATION_MARKER_NOTE,
        ).order_by("user_id")
    )

    for marker in markers:
        user_id = marker.user_id
        old_legacy_balance = int(marker.balance_after)
        corrected_legacy_balance = _rub_balance_to_coins(old_legacy_balance)

        legacy_transactions = CoinTransaction.objects.filter(
            user_id=user_id,
            created_at__lte=cutover_at,
        ).exclude(pk=marker.pk)
        for transaction in legacy_transactions.order_by("id").iterator():
            CoinTransaction.objects.filter(pk=transaction.pk).update(
                amount=_related_coin_amount(apps, transaction),
                balance_after=_rub_balance_to_coins(transaction.balance_after),
                note=_legacy_note(transaction.kind, transaction.note),
            )

        wallet = CoinWallet.objects.filter(user_id=user_id).first()
        if wallet:
            corrected_current = _corrected_wallet_balance(
                wallet.balance,
                old_legacy_balance,
            )
            CoinWallet.objects.filter(pk=wallet.pk).update(
                balance=corrected_current,
            )

        CoinTransaction.objects.filter(pk=marker.pk).update(
            balance_after=corrected_legacy_balance,
            note=NEW_MIGRATION_MARKER_NOTE,
        )


def apply_historical_coin_rate(apps, schema_editor):
    cutover_at = _migration_applied_at(schema_editor)
    if cutover_at is None:
        return

    _convert_legacy_coupons(apps, cutover_at)
    _convert_legacy_copied_bets(apps, cutover_at)
    _convert_copybetting_settings_and_totals(apps, cutover_at)
    _repair_already_migrated_wallets_and_ledger(apps, cutover_at)
    _rebuild_capper_bank_stats(apps)
    _rebuild_tournament_coin_results(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0009_remove_legacy_virtual_balance"),
        ("game", "0023_predictioncoverimage_placement"),
        ("tournaments", "0002_alter_tournament_min_confidence"),
    ]

    operations = [
        migrations.RunPython(
            apply_historical_coin_rate,
            migrations.RunPython.noop,
        ),
    ]
