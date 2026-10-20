from django.core.management.base import BaseCommand
from django.db import transaction

from front.metric_models import PredictionMetrics, PredictionCouponOpen


class Command(BaseCommand):
    help = "Пересчитать уникальные открытия из записей читателей, включая обезличенные."

    def handle(self, *args, **options):
        updated = 0
        for pk in PredictionMetrics.objects.order_by("pk").values_list("pk", flat=True).iterator(chunk_size=500):
            with transaction.atomic():
                metrics = PredictionMetrics.objects.select_for_update().get(pk=pk)
                metrics.unique_opens_count = PredictionCouponOpen.objects.filter(coupon_id=metrics.coupon_id).count()
                metrics.save(update_fields=["unique_opens_count", "updated_at"])
            updated += 1
        self.stdout.write(self.style.SUCCESS(f"Пересчитано купонов: {updated}"))
