import json
import logging
import random
import signal
import threading
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from redis import Redis
from redis.exceptions import LockError
from websockets.sync.client import connect

from game.services.live_stream import LiveMessageError, LiveStateStream, live_sport_ids, validate_snapshot
from game.services.live_stream_health import LiveStreamHealth


def websocket_url():
    parsed = urlsplit(settings.NEUROKEFF_LIVE_WS_URL)
    if parsed.scheme != "wss" or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        raise CommandError("NEUROKEFF_LIVE_WS_URL must be a wss URL without credentials or query parameters")
    query = urlencode({"sport": ",".join(map(str, sorted(live_sport_ids())))})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def queue_reconciliation(game_ids):
    from game.tasks import refresh_live_match_states

    # Suppress repeated discovery/reconciliation requests during reconnect storms.
    selected = [game_id for game_id in game_ids if cache.add(f"live-ws:refresh:{game_id}", 1, timeout=60)]
    if not selected:
        return
    # Bound the HTTP/transaction work of each task, including large reconnect snapshots.
    for offset in range(0, len(selected), 50):
        try:
            refresh_live_match_states.apply_async(args=[selected[offset:offset + 50]], retry=False)
        except Exception:
            cache.delete_many([f"live-ws:refresh:{game_id}" for game_id in selected[offset:]])
            raise


def monitor_connection(socket, health, stopped, consumer_stopped=None):
    """Confirm liveness independently of potentially slow snapshot DB writes."""
    try:
        while not stopped.wait(10):
            if consumer_stopped is not None and consumer_stopped.is_set():
                return
            if not socket.ping().wait(timeout=5):
                raise TimeoutError("Live WebSocket pong timed out")
            if not stopped.is_set() and (consumer_stopped is None or not consumer_stopped.is_set()):
                health.mark_alive()
    except Exception:
        stopped.set()
        health.clear()
        try:
            socket.close()
        except Exception:
            pass
    finally:
        health.clear()


class Command(BaseCommand):
    help = "Слушать Neurokeff live WebSocket (только состояние матчей)."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="Проверить handshake и snapshot без записи в БД.")

    def handle(self, *args, **options):
        if not settings.NEUROKEFF_API_TOKEN:
            raise CommandError("NEUROKEFF_API_TOKEN is not configured")
        url = websocket_url()
        stop = threading.Event()
        previous_handlers = {}
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, lambda *_: stop.set())
        # Never allow transport debug logs to print Authorization headers.
        transport_log = logging.getLogger("game.live_ws.transport")
        transport_log.setLevel(logging.WARNING)
        lease = None
        lease_acquired = False
        lease_lost = threading.Event()
        lease_thread = None
        try:
            if not options["check"]:
                lease = Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=5, socket_connect_timeout=5).lock(
                    "neurokeff:live-ws:consumer", timeout=60, thread_local=False,
                )
                if not lease.acquire(blocking=False):
                    raise CommandError("Another Neurokeff live consumer already owns the lease")
                lease_acquired = True

                def renew_lease():
                    # Renew even while a large snapshot is being applied to the DB.
                    while not stop.wait(10):
                        try:
                            lease.extend(60, replace_ttl=True)
                        except Exception:
                            lease_lost.set()
                            stop.set()

                lease_thread = threading.Thread(target=renew_lease, name="live-ws-lease", daemon=True)
                lease_thread.start()
            failures = 0
            while not stop.is_set():
                health = LiveStreamHealth()
                stream = LiveStateStream(session_id=health.session_id)
                connection_stopped = threading.Event()
                health_thread = None
                started = time.monotonic()
                last_live_message = started
                got_snapshot = False
                try:
                    with connect(url, additional_headers={"Authorization": f"Token {settings.NEUROKEFF_API_TOKEN}"},
                                 proxy=None, open_timeout=10, close_timeout=3, ping_interval=20, ping_timeout=20,
                                 max_size=4 * 1024 * 1024, max_queue=16, logger=transport_log) as socket:
                        self.stdout.write("Live WebSocket connected; waiting for snapshot.")
                        while not stop.is_set() and not connection_stopped.is_set():
                            # Protocol pong alone doesn't prove that the provider's
                            # live publisher is still delivering match state.
                            if got_snapshot and time.monotonic() - last_live_message > 90:
                                raise LiveMessageError("Live state feed stalled; requesting a new snapshot")
                            try:
                                raw = socket.recv(timeout=5)
                            except TimeoutError:
                                if not got_snapshot and time.monotonic() - started > 30:
                                    raise LiveMessageError("Initial snapshot timed out")
                                continue
                            message = json.loads(raw)
                            if not isinstance(message, dict):
                                raise LiveMessageError("Message is not an object")
                            if not got_snapshot and message.get("type") != "live.snapshot":
                                if message.get("type") == "pong":
                                    continue
                                raise LiveMessageError("Expected initial live snapshot")
                            if options["check"]:
                                # Validate schema without allowing the applier to write anything.
                                validate_snapshot(message)
                                if not socket.ping().wait(timeout=5):
                                    raise LiveMessageError("Live WebSocket pong timed out")
                                self.stdout.write(self.style.SUCCESS(f"Valid live snapshot: {len(message['matches'])} matches. No database writes."))
                                return
                            if not got_snapshot:
                                validate_snapshot(message)
                                # Publish before applying rows: once a row gets
                                # this session ID, REST must already see ownership.
                                health.mark_alive()
                                health_thread = threading.Thread(
                                    target=monitor_connection, args=(socket, health, connection_stopped, stop),
                                    name="live-ws-health", daemon=True,
                                )
                                health_thread.start()
                            close_old_connections()
                            result = stream.apply_message(message)
                            if message.get("type") != "pong":
                                last_live_message = time.monotonic()
                            if message.get("type") == "live.snapshot":
                                got_snapshot = True
                                failures = 0
                                self.stdout.write(f"Live snapshot applied: {result['updated']} updated; {len(result['refresh_ids'])} require REST reconciliation.")
                            if result["refresh_ids"]:
                                queue_reconciliation(result["refresh_ids"])
                except LockError:
                    raise CommandError("Live consumer lease lost; stopping to avoid duplicate consumers") from None
                except Exception as exc:
                    close_old_connections()
                    code = getattr(getattr(exc, "rcvd", None), "code", None)
                    http_status = getattr(getattr(exc, "response", None), "status_code", None)
                    # Only class and numeric codes: exception text may contain secrets.
                    reason = f"{type(exc).__name__}; close={code}; http={http_status}"
                    if options["check"] or code in (4401, 4403) or http_status in (401, 403):
                        raise CommandError(f"Live WebSocket unavailable ({reason}). Check API token/subscription and provider availability.") from None
                    self.stderr.write(f"Live WebSocket disconnected ({reason}); reconnecting.")
                    failures += 1
                finally:
                    connection_stopped.set()
                    if health_thread:
                        health_thread.join(timeout=6)
                    if not options["check"]:
                        health.clear()
                    close_old_connections()
                if lease_lost.is_set():
                    raise CommandError("Live consumer lease lost; stopping to avoid duplicate consumers")
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
