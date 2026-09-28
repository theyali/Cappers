#!/usr/bin/env sh
set -e

is_true() {
  case "${1:-}" in
    1|true|True|yes|Yes|on|On)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

ensure_log_dir() {
  mkdir -p "${LOG_DIR:-/app/logging}"
}

run_with_optional_file_logs() {
  ensure_log_dir

  if [ -n "${APP_STDOUT_LOG:-}" ]; then
    mkdir -p "$(dirname "${APP_STDOUT_LOG}")"
  fi
  if [ -n "${APP_STDERR_LOG:-}" ]; then
    mkdir -p "$(dirname "${APP_STDERR_LOG}")"
  fi

  if [ -n "${APP_STDOUT_LOG:-}" ] || [ -n "${APP_STDERR_LOG:-}" ]; then
    LOG_STDOUT_TARGET="${APP_STDOUT_LOG:-/dev/stdout}"
    LOG_STDERR_TARGET="${APP_STDERR_LOG:-/dev/stderr}"
    export LOG_STDOUT_TARGET LOG_STDERR_TARGET
    exec sh -c 'exec "$@" >>"$LOG_STDOUT_TARGET" 2>>"$LOG_STDERR_TARGET"' sh "$@"
  fi

  exec "$@"
}

ensure_log_dir

# 1) миграции — только если включено
if is_true "${RUN_MIGRATIONS:-0}"; then
  python manage.py migrate --noinput
fi

# 1.1) collectstatic — если явно включили RUN_COLLECTSTATIC
# или, для обратной совместимости, когда DEBUG выключен и флаг не задан
if [ -n "${RUN_COLLECTSTATIC:-}" ]; then
  SHOULD_COLLECTSTATIC=0
  if is_true "${RUN_COLLECTSTATIC:-0}"; then
    SHOULD_COLLECTSTATIC=1
  fi
else
  SHOULD_COLLECTSTATIC=1
  if is_true "${DEBUG:-0}"; then
    SHOULD_COLLECTSTATIC=0
  fi
fi

if [ "$SHOULD_COLLECTSTATIC" = "1" ]; then
  python manage.py collectstatic --noinput
fi

# 2) если передали команду (worker/beat/web через compose) — запускаем её
if [ "$#" -gt 0 ]; then
  run_with_optional_file_logs "$@"
fi

# 3) fallback: если команду не передали — запускаем web с учетом DEBUG
PORT="${PORT:-8000}"

if [ "${DEBUG:-0}" = "1" ] || [ "${DEBUG:-0}" = "true" ] || [ "${DEBUG:-0}" = "True" ]; then
  set -- python manage.py runserver 0.0.0.0:${PORT}
else
  set -- uvicorn analitika_aleksey.asgi:application --host 0.0.0.0 --port ${PORT} --workers ${UVICORN_WORKERS:-2}
fi

run_with_optional_file_logs "$@"
