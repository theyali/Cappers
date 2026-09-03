from django.core.management.base import BaseCommand, CommandError

from game.models import PredictionCoupon
from game.services.settlement import resettle_coupon, settle_coupon


class Command(BaseCommand):
    help = "Recalculate coupon prediction states and repair wallet settlement transactions."

    def add_arguments(self, parser):
        parser.add_argument("coupon_ids", nargs="+", type=int)
        parser.add_argument(
            "--no-recalculate-predictions",
            action="store_true",
            help="Only repair coupon-level settlement and wallet ledger.",
        )

    def handle(self, *args, **options):
        coupon_ids = options["coupon_ids"]
        recalculate = not options["no_recalculate_predictions"]
        missing_ids = set(coupon_ids) - set(
            PredictionCoupon.objects.filter(pk__in=coupon_ids).values_list("pk", flat=True)
        )
        if missing_ids:
            raise CommandError(
                "Купоны не найдены: " + ", ".join(str(pk) for pk in sorted(missing_ids))
            )

        for coupon_id in coupon_ids:
            before = PredictionCoupon.objects.get(pk=coupon_id)
            before_state = before.state_status
            before_settled_at = before.settled_at
            coupon = (
                resettle_coupon(coupon_id, recalculate_predictions=True)
                if recalculate
                else settle_coupon(coupon_id)
            )
            if coupon is None:
                continue
            self.stdout.write(
                self.style.SUCCESS(
                    f"coupon #{coupon.pk}: {before_state} -> {coupon.state_status}; "
                    f"settled_at {before_settled_at or '-'} -> {coupon.settled_at or '-'}"
                )
            )
