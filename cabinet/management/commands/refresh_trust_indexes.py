from django.core.management.base import BaseCommand, CommandError

from cabinet.models import AnalystProfile, User
from cabinet.trust_index import refresh_capper_trust_index


class Command(BaseCommand):
    help = "Recalculate and persist trust indexes for capper profiles."

    def add_arguments(self, parser):
        parser.add_argument("analyst_ids", nargs="*", type=int)
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        analyst_ids = options["analyst_ids"]
        queryset = AnalystProfile.objects.filter(
            user__role=User.Role.ANALYST,
        ).select_related("user")

        if analyst_ids:
            existing_ids = set(
                queryset.filter(user_id__in=analyst_ids).values_list("user_id", flat=True)
            )
            missing_ids = set(analyst_ids) - existing_ids
            if missing_ids:
                raise CommandError(
                    "Капперы не найдены: "
                    + ", ".join(str(pk) for pk in sorted(missing_ids))
                )
            queryset = queryset.filter(user_id__in=analyst_ids)

        queryset = queryset.order_by("user_id")
        limit = max(0, int(options["limit"] or 0))
        if limit:
            queryset = queryset[:limit]

        updated = 0
        for profile in queryset.iterator():
            refresh_capper_trust_index(profile.user_id)
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"Индексы доверия пересчитаны: {updated}"))
