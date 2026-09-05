from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from bots.models import BotAccount
from bots.services import _is_zero_handicap_selection, _total_line_reasonable
from game.models import Prediction, PredictionCoupon


class Command(BaseCommand):
    help = "Находит и отменяет опубликованные бот-купоны с неадекватными рынками или коэффициентами."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Применить изменения. Без флага команда работает в режиме dry-run.",
        )
        parser.add_argument(
            "--max-coefficient",
            type=Decimal,
            default=Decimal("5.00"),
            help="Максимальный допустимый коэффициент позиции для уже созданных бот-прогнозов.",
        )
        parser.add_argument(
            "--include-settled",
            action="store_true",
            help="Также проверять рассчитанные купоны. По умолчанию затрагиваются только ожидающие.",
        )
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options):
        max_coefficient = options["max_coefficient"]
        queryset = (
            Prediction.objects.select_related("coupon", "coupon__author", "match")
            .filter(
                coupon__author__bot_account__kind=BotAccount.Kind.EXPERT,
                coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            )
            .order_by("-created_at", "-id")
        )
        if not options["include_settled"]:
            queryset = queryset.filter(coupon__state_status=PredictionCoupon.StateStatus.PENDING)
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        bad_coupon_ids = set()
        reasons_by_coupon = {}
        for prediction in queryset:
            reasons = _bad_prediction_reasons(prediction, max_coefficient)
            if not reasons:
                continue
            bad_coupon_ids.add(prediction.coupon_id)
            reasons_by_coupon.setdefault(prediction.coupon_id, set()).update(reasons)

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run: найдено {len(bad_coupon_ids)} купонов. "
                    "Запустите с --apply, чтобы отменить их."
                )
            )
            for coupon_id in sorted(bad_coupon_ids):
                self.stdout.write(f"#{coupon_id}: {', '.join(sorted(reasons_by_coupon[coupon_id]))}")
            return

        with transaction.atomic():
            updated = PredictionCoupon.objects.filter(id__in=bad_coupon_ids).update(
                published_status=PredictionCoupon.PublishedStatus.CANCELED
            )

        self.stdout.write(self.style.SUCCESS(f"Отменено купонов: {updated}"))


def _bad_prediction_reasons(prediction: Prediction, max_coefficient: Decimal) -> list[str]:
    reasons = []
    if prediction.coefficient > max_coefficient:
        reasons.append(f"coefficient>{max_coefficient}")
    if prediction.market == "handicap" and _is_zero_handicap_selection(prediction.selection):
        reasons.append("zero_handicap")
    if prediction.market == "total" and not _total_line_reasonable(prediction.match, prediction.selection):
        reasons.append("unrealistic_total")
    return reasons
