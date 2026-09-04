from django.core.management.base import BaseCommand, CommandError

from game.models import PredictionCoupon
from wallets.models import CopiedBet
from wallets.services import settle_orphaned_copied_bets, settle_prediction_coupon


class Command(BaseCommand):
    help = "Settle copied bets that are still pending while their source coupon is already settled."

    def add_arguments(self, parser):
        parser.add_argument("coupon_ids", nargs="*", type=int)
        parser.add_argument("--limit", type=int, default=1000)

    def handle(self, *args, **options):
        coupon_ids = options["coupon_ids"]
        if coupon_ids:
            existing_ids = set(
                PredictionCoupon.objects.filter(pk__in=coupon_ids).values_list("pk", flat=True)
            )
            missing_ids = set(coupon_ids) - existing_ids
            if missing_ids:
                raise CommandError(
                    "Купоны не найдены: " + ", ".join(str(pk) for pk in sorted(missing_ids))
                )

            settled_count = 0
            for coupon in PredictionCoupon.objects.filter(pk__in=coupon_ids).select_related("author"):
                before_count = CopiedBet.objects.filter(
                    source_coupon=coupon,
                    state_status=CopiedBet.StateStatus.PENDING,
                ).count()
                settle_prediction_coupon(coupon)
                after_count = CopiedBet.objects.filter(
                    source_coupon=coupon,
                    state_status=CopiedBet.StateStatus.PENDING,
                ).count()
                settled_count += max(0, before_count - after_count)
            self.stdout.write(
                self.style.SUCCESS(f"Settled copied bets for selected coupons: {settled_count}")
            )
            return

        settled_count = settle_orphaned_copied_bets(limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(f"Settled orphaned copied bets: {settled_count}")
        )
