from django.core.management.base import BaseCommand

from cabinet.models import CapperMonthlyStat
from front.expert_ranking import (
    ALL_SPORTS,
    ALL_TIME,
    ROI_PERIOD_DAYS,
    current_month_start,
    rebuild_expert_ranking_snapshot,
    refresh_core_expert_rankings,
)


class Command(BaseCommand):
    help = "Rebuild materialized expert ranking snapshots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--period",
            action="append",
            help="Ranking period to rebuild, e.g. all-time or 2026-09. Can be repeated.",
        )
        parser.add_argument(
            "--sport-code",
            default=ALL_SPORTS,
            help="Sport code for a single snapshot rebuild. Default: all.",
        )
        parser.add_argument(
            "--group",
            default="all",
            help="Ranking group for a single snapshot rebuild. Default: all.",
        )
        parser.add_argument(
            "--roi-period-days",
            type=int,
            default=None,
            help="Display ROI period for all-time profile snapshots.",
        )
        parser.add_argument(
            "--core",
            action="store_true",
            help="Rebuild only homepage/core snapshots: all-time, current month and default ROI period.",
        )

    def handle(self, *args, **options):
        periods = options["period"] or []
        if options["core"]:
            refresh_core_expert_rankings(periods=periods)
            current_month = current_month_start().strftime("%Y-%m")
            self.stdout.write(
                self.style.SUCCESS(
                    "Rebuilt core expert ranking snapshots "
                    f"(all-time, {current_month}, {ROI_PERIOD_DAYS}d ROI)."
                )
            )
            return

        if not periods:
            periods = [
                value.strftime("%Y-%m")
                for value in CapperMonthlyStat.objects.order_by("month")
                .values_list("month", flat=True)
                .distinct()
            ]
            refresh_core_expert_rankings(periods=periods)
            self.stdout.write(
                self.style.SUCCESS(
                    "Rebuilt expert ranking snapshots for all-time, current month, "
                    f"{ROI_PERIOD_DAYS}d ROI and {len(periods)} historical months."
                )
            )
            return

        for period in periods:
            snapshot = rebuild_expert_ranking_snapshot(
                period=period or ALL_TIME,
                sport_code=options["sport_code"],
                group=options["group"],
                roi_period_days=options["roi_period_days"],
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Rebuilt {snapshot} with {snapshot.entries_count} entries."
                )
            )
