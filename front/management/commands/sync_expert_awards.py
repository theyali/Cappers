from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from front.expert_awards import (
    check_expert_awards,
    close_due_award_months,
    finalize_monthly_awards,
)
from front.expert_ranking import rank_experts, rebuild_expert_ranking_snapshot


class Command(BaseCommand):
    help = "Preview/check leader badges without writes; --apply explicitly starts observation/sync or backfills one month."

    def add_arguments(self, parser):
        parser.add_argument(
            "--month",
            help="YYYY-MM: preview or explicitly backfill this closed month only.",
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--apply",
            action="store_true",
            help="Write awards. Without it the command is read-only.",
        )
        mode.add_argument(
            "--check",
            action="store_true",
            help="Check registry integrity and Beat schedule without writes.",
        )
        parser.add_argument(
            "--check-workers",
            action="store_true",
            help="With --check, also inspect registered tasks on running workers.",
        )

    def handle(self, *args, **options):
        if options["check_workers"] and not options["check"]:
            raise CommandError("--check-workers используется только вместе с --check.")
        if options["check"]:
            if options["month"]:
                raise CommandError(
                    "--check проверяет весь реестр; не совмещайте его с --month."
                )
            report = check_expert_awards()
            if options["check_workers"]:
                from cappers.celery import app

                required = {
                    "front.tasks.refresh_expert_rankings_task",
                    "front.tasks.close_expert_award_months_task",
                }
                try:
                    workers = app.control.inspect(timeout=5).registered() or {}
                except Exception:
                    # Broker exception text may contain connection credentials.
                    raise CommandError(
                        "Не удалось опросить worker; проверьте доступность Celery и брокера."
                    ) from None
                if not workers:
                    report["errors"].append(
                        "Ни один worker не ответил на проверку регистрации задач."
                    )
                elif not any(
                    required.issubset(set(tasks)) for tasks in workers.values()
                ):
                    report["errors"].append(
                        "Нет работающего worker с обеими задачами рейтинга и закрытия месяца."
                    )
                for tasks in workers.values():
                    if required.intersection(tasks) and not required.issubset(
                        set(tasks)
                    ):
                        report["errors"].append(
                            "Один из worker рейтинга работает с неполным набором задач; обновите его."
                        )
            self.stdout.write(
                f"CHECK · без изменения данных. All-time: {report['active_all_time']}, месяцев: {report['monthly_periods']}, активных месячных медалей: {report['monthly_awards']}."
            )
            for warning in report["warnings"]:
                self.stdout.write(self.style.WARNING(warning))
            for error in report["errors"]:
                self.stderr.write(self.style.ERROR(error))
            if report["errors"]:
                raise CommandError(
                    f"Проверка наград не пройдена: ошибок {len(report['errors'])}."
                )
            self.stdout.write(
                self.style.SUCCESS("Реестр наград и расписание согласованы.")
            )
            return
        month = None
        if options["month"]:
            try:
                month = datetime.strptime(options["month"], "%Y-%m").date()
            except ValueError as exc:
                raise CommandError("Месяц должен быть в формате YYYY-MM.") from exc
        if not options["apply"]:
            period = month.strftime("%Y-%m") if month else "all-time"
            self.stdout.write(
                f"DRY RUN · {period}. Записей в БД не создаётся. Месячные результаты перед реальной выдачей будут пересчитаны."
            )
            for entry in rank_experts(period=period, limit=3 if month else 10):
                self.stdout.write(
                    f"#{entry['rank']} · user={entry['profile'].user_id} · {entry['profile'].user.username}"
                )
            return
        try:
            if month:
                period = finalize_monthly_awards(month, source="backfill")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{period}: редакция {period.revision}, участников {period.eligible_count}."
                    )
                )
            else:
                rebuild_expert_ranking_snapshot(period="all-time")
                closed = close_due_award_months()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"All-time синхронизирован. Закрытые месяцы: {', '.join(closed) or 'нет'}."
                    )
                )
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
