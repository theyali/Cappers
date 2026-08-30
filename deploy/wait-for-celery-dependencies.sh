#!/bin/sh
set -e

: "${WAIT_FOR_SERVICES_TIMEOUT:=120}"
: "${WAIT_FOR_SERVICES_INTERVAL:=2}"

wait_until() {
  name="$1"
  shift
  start_time="$(date +%s)"

  while true; do
    if "$@" >/dev/null 2>&1; then
      echo "$name is ready."
      return 0
    fi

    now="$(date +%s)"
    elapsed=$((now - start_time))
    if [ "$elapsed" -ge "$WAIT_FOR_SERVICES_TIMEOUT" ]; then
      echo "Timed out waiting for $name after ${WAIT_FOR_SERVICES_TIMEOUT}s." >&2
      return 1
    fi

    echo "Waiting for $name..."
    sleep "$WAIT_FOR_SERVICES_INTERVAL"
  done
}

check_redis() {
  python - <<'PY'
import os

from redis import Redis

url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
Redis.from_url(url).ping()
PY
}

wait_until "database migrations" python manage.py migrate --check --noinput
wait_until "redis" check_redis

exec "$@"
