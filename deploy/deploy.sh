#!/usr/bin/env bash
set -euo pipefail

compose() {
  docker compose "$@"
}

DEPLOY_BUILD="${DEPLOY_BUILD:-0}"
DEPLOY_FULL_RECREATE="${DEPLOY_FULL_RECREATE:-0}"
DEPLOY_RESTART_APP="${DEPLOY_RESTART_APP:-1}"
DEPLOY_RESTART_NGINX="${DEPLOY_RESTART_NGINX:-0}"
DEPLOY_PRUNE="${DEPLOY_PRUNE:-0}"

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-cappershub}"

if [ ! -f ".env" ]; then
  echo ".env is missing in $(pwd). Create it before deploying." >&2
  exit 1
fi

chmod +x entrypoint.sh deploy/*.sh

if [ "${DEPLOY_FULL_RECREATE}" = "1" ]; then
  compose up -d --build --remove-orphans db redis pgbouncer
elif [ "${DEPLOY_BUILD}" = "1" ]; then
  compose build
  compose up -d --remove-orphans db redis pgbouncer
else
  compose up -d --remove-orphans db redis pgbouncer
fi

compose run --rm migrate

if [ "${DEPLOY_RESTART_APP}" = "1" ] || [ "${DEPLOY_FULL_RECREATE}" = "1" ] || [ "${DEPLOY_BUILD}" = "1" ]; then
  compose up -d --build --remove-orphans web celery celery-beat telegram-bot
fi

if [ "${DEPLOY_RESTART_NGINX}" = "1" ] && command -v nginx >/dev/null 2>&1; then
  sudo nginx -t
  sudo systemctl reload nginx
fi

if [ "${DEPLOY_PRUNE}" = "1" ]; then
  docker image prune -f
fi

compose ps
