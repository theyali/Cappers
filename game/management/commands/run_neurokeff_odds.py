import json
import logging
import random
import signal
import threading
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from redis import Redis
from redis.exceptions import LockError
from websockets.sync.client import connect

from game.services.odds_stream import (
    OddsMessageError,
    odds_sport_ids,
    queue_odds_message,
    queue_prematch_reconciliation,
)


def websocket_url(sport_ids):
    parsed = urlsplit(settings.NEUROKEFF_ODDS_WS_URL)
    if parsed.scheme != "wss" or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        raise CommandError("NEUROKEFF_ODDS_WS_URL must be a wss URL without credentials or query parameters")
    query = urlencode({"sport": ",".join(map(str, sorted(sport_ids)))})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


class Command(BaseCommand):
    help = "Слушать Neurokeff prematch.odds.available/updated и ставить REST-загрузку КФ в очередь."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="Проверить handshake и pong без БД и очередей.")

    def handle(self, *args, **options):
        if not settings.NEUROKEFF_API_TOKEN:
            raise CommandError("NEUROKEFF_API_TOKEN is not configured")
        sport_ids = odds_sport_ids()
        url = websocket_url(sport_ids)
        stop = threading.Event()
        lease_lost = threading.Event()
        previous_handlers = {}
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, lambda *_: stop.set())
        transport_log = logging.getLogger("game.odds_ws.transport")
        transport_log.setLevel(logging.WARNING)
        lease = None
        lease_acquired = False
        lease_thread = None
        try:
            if not options["check"]:
                lease = Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=5, socket_connect_timeout=5).lock(
                    "neurokeff:odds-ws:consumer", timeout=60, thread_local=False,
                )
                if not lease.acquire(blocking=False):
                    raise CommandError("Another Neurokeff odds consumer already owns the lease")
                lease_acquired = True

                def renew_lease():
                    while not stop.wait(10):
                        try:
                            lease.extend(60, replace_ttl=True)
                        except Exception:
                            lease_lost.set()
                            stop.set()

                lease_thread = threading.Thread(target=renew_lease, name="odds-ws-lease", daemon=True)
                lease_thread.start()
            failures = 0
            while not stop.is_set():
                connected_at = time.monotonic()
                try:
                    with connect(url, additional_headers={"Authorization": f"Token {settings.NEUROKEFF_API_TOKEN}"},
                                 proxy=None, open_timeout=10, close_timeout=3, ping_interval=20, ping_timeout=20,
                                 max_size=65536, max_queue=16, logger=transport_log) as socket:
                        if not socket.ping().wait(timeout=5):
                            raise TimeoutError("Odds WebSocket pong timed out")
                        if options["check"]:
                            self.stdout.write(self.style.SUCCESS("Odds WebSocket handshake/pong OK. No database writes or queued tasks."))
                            return
                        if stop.is_set():
                            break
                        # This channel has NO snapshot/replay, including the first
                        # connection. REST work must not block receiving WS events.
                        queued = queue_prematch_reconciliation(sport_ids)
                        self.stdout.write(f"Odds WebSocket connected; {queued} prematch REST reconciliations queued.")
                        while not stop.is_set():
                            try:
                                raw = socket.recv(timeout=5)
                            except TimeoutError:
                                continue  # A quiet availability channel is healthy.
                            try:
                                message = json.loads(raw)
                                if not isinstance(message, dict):
                                    raise OddsMessageError("Message is not an object")
                                if message.get("type") == "pong":
                                    continue
                                if message.get("type") == "ping":
                                    socket.send('{"type":"pong"}')
                                    continue
                                if stop.is_set():
                                    break
                                if queue_odds_message(message, sport_ids):
                                    self.stdout.write(f"Prematch odds REST refresh queued: game_pk={message['game_pk']}; type={message['type']}.")
                            except (json.JSONDecodeError, UnicodeDecodeError, OddsMessageError):
                                self.stderr.write("Invalid or unsupported odds notification ignored.")
                except Exception as exc:
                    code = getattr(getattr(exc, "rcvd", None), "code", None)
                    http_status = getattr(getattr(exc, "response", None), "status_code", None)
                    # Never log exception text/headers: they may expose the token.
                    reason = f"{type(exc).__name__}; close={code}; http={http_status}"
                    if options["check"] or code in (4401, 4403) or http_status in (401, 403):
                        raise CommandError(f"Odds WebSocket unavailable ({reason}). Check token/subscription and provider availability.") from None
                    self.stderr.write(f"Odds WebSocket disconnected ({reason}); reconnecting.")
                    failures = 0 if time.monotonic() - connected_at > 30 else failures
                    failures += 1
                finally:
                    close_old_connections()
                if lease_lost.is_set():
                    raise CommandError("Odds consumer lease lost; stopping")
                stop.wait(min(30, 2 ** max(0, min(failures - 1, 5)) + random.uniform(0, 1)))
        finally:
            stop.set()
            if lease_thread:
                lease_thread.join(timeout=6)
            if lease_acquired:
                try:
                    lease.release()
                except LockError:
                    pass
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
