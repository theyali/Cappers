from time import perf_counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse


TARGETS = (
    ("home", "front:index", False),
    ("predictions", "front:predictions", False),
    ("feed", "front:following_feed", True),
    ("cappers-table", "front:cappers_table", False),
    ("tournaments", "tournaments:index", False),
)


class Command(BaseCommand):
    help = "Measure cold/warm SQL count, SQL time and response time for public performance targets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            help="Existing user used for authenticated targets such as /feed/.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow running outside DEBUG. Prefer local/staging because cold runs clear Django cache.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "SQL audit clears Django cache. Run with DEBUG=True on local/staging, "
                "or pass --force explicitly."
            )

        user = None
        username = (options.get("username") or "").strip()
        if username:
            user = get_user_model().objects.filter(username=username).first()
            if user is None:
                raise CommandError(f"User @{username} was not found.")

        self.stdout.write(
            "target\tmode\tstatus\tsql_count\tsql_ms\tresponse_ms"
        )
        with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
            for label, url_name, requires_auth in TARGETS:
                if requires_auth and user is None:
                    self.stdout.write(
                        f"{label}\tskipped\t-\t-\t-\t-\t(use --username for authenticated feed)"
                    )
                    continue

                cache.clear()
                client = Client()
                if user is not None:
                    client.force_login(user)

                url = reverse(url_name)
                cold = self._measure(client, url)
                warm = self._measure(client, url)
                self._print_result(label, "cold", cold)
                self._print_result(label, "warm", warm)

    @staticmethod
    def _measure(client: Client, url: str) -> dict:
        with CaptureQueriesContext(connection) as queries:
            started = perf_counter()
            response = client.get(url)
            response_ms = (perf_counter() - started) * 1000

        sql_ms = 0.0
        for query in queries.captured_queries:
            try:
                sql_ms += float(query.get("time") or 0) * 1000
            except (TypeError, ValueError):
                continue

        return {
            "status": response.status_code,
            "sql_count": len(queries.captured_queries),
            "sql_ms": sql_ms,
            "response_ms": response_ms,
        }

    def _print_result(self, label: str, mode: str, result: dict) -> None:
        self.stdout.write(
            f"{label}\t{mode}\t{result['status']}\t{result['sql_count']}\t"
            f"{result['sql_ms']:.2f}\t{result['response_ms']:.2f}"
        )
