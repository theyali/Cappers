#!/usr/bin/env bash
set -euo pipefail

compose() {
  # Include both WS consumers so --remove-orphans won't delete them.
  # Starting them remains opt-in via DEPLOY_LIVE_WS below.
  docker compose --profile live "$@"
}

DEPLOY_BUILD="${DEPLOY_BUILD:-0}"
DEPLOY_FULL_RECREATE="${DEPLOY_FULL_RECREATE:-0}"
DEPLOY_RESTART_APP="${DEPLOY_RESTART_APP:-1}"
DEPLOY_RESTART_NGINX="${DEPLOY_RESTART_NGINX:-0}"
DEPLOY_PRUNE="${DEPLOY_PRUNE:-0}"
DEPLOY_LIVE_WS="${DEPLOY_LIVE_WS:-0}"

# Project name comes from docker-compose.yml, just like manual compose commands.
# An explicit COMPOSE_PROJECT_NAME in the shell/.env can still override it.

if [ ! -f ".env" ]; then
  echo ".env is missing in $(pwd). Create it before deploying." >&2
  exit 1
fi

chmod +x entrypoint.sh deploy/*.sh

target_revision="$(git rev-parse HEAD)"
deployed_revision_file="$(git rev-parse --git-path cappers-deployed-revision)"

# Build once, only when the workflow requests it (or for a full deploy).
# Source changes are already mounted into /app and only need fresh processes.
if [ "${DEPLOY_BUILD}" = "1" ] || [ "${DEPLOY_FULL_RECREATE}" = "1" ]; then
  compose build
fi
compose up -d --no-build --remove-orphans db redis pgbouncer

compose run --rm migrate

app_up_options=(-d --no-build --no-deps --wait --wait-timeout 120)
if [ "${DEPLOY_RESTART_APP}" = "1" ] || [ "${DEPLOY_FULL_RECREATE}" = "1" ] || [ "${DEPLOY_BUILD}" = "1" ]; then
  # up alone does not restart unchanged containers after a bind-mounted code update.
  # Dependencies and migrations have already been started above.
  app_up_options+=(--force-recreate)
  compose up "${app_up_options[@]}" web celery celery-beat telegram-bot
fi

# Ensure both consumers run even when this deploy does not restart the app.
if [ "${DEPLOY_LIVE_WS}" = "1" ]; then
  compose up "${app_up_options[@]}" neurokeff-live neurokeff-odds
fi

if [ "${DEPLOY_RESTART_NGINX}" = "1" ] && command -v nginx >/dev/null 2>&1; then
  NGINX_SOURCE_CONFIG="deploy/nginx/cuppershub.com.conf"
  NGINX_ACTIVE_CONFIG="${NGINX_SITE_CONFIG:-}"

  if [ -z "${NGINX_ACTIVE_CONFIG}" ]; then
    for candidate in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
      if [ -f "${candidate}" ] && grep -Eq 'server_name .*capper-hub\.com' "${candidate}"; then
        NGINX_ACTIVE_CONFIG="${candidate}"
        break
      fi
    done
  fi

  if [ -z "${NGINX_ACTIVE_CONFIG}" ]; then
    echo "Could not find the active capper-hub.com nginx config." >&2
    exit 1
  fi

  NGINX_ACTIVE_CONFIG="$(readlink -f "${NGINX_ACTIVE_CONFIG}")"
  case "${NGINX_ACTIVE_CONFIG}" in
    /etc/nginx/*) ;;
    *)
      echo "Refusing to replace nginx config outside /etc/nginx: ${NGINX_ACTIVE_CONFIG}" >&2
      exit 1
      ;;
  esac

  NGINX_ACTIVE_RELATIVE="${NGINX_ACTIVE_CONFIG#/etc/nginx/}"
  docker run --rm \
    --entrypoint /bin/sh \
    -e NGINX_ACTIVE_RELATIVE="${NGINX_ACTIVE_RELATIVE}" \
    -v "$(pwd)/${NGINX_SOURCE_CONFIG}:/source.conf:ro" \
    -v /etc/nginx:/target \
    postgres:16-alpine \
    -c 'set -e; cp "/target/${NGINX_ACTIVE_RELATIVE}" "/target/${NGINX_ACTIVE_RELATIVE}.cappers-backup"; cp /source.conf "/target/${NGINX_ACTIVE_RELATIVE}"; chmod 0644 "/target/${NGINX_ACTIVE_RELATIVE}"'
  if ! sudo nginx -t; then
    docker run --rm \
      --entrypoint /bin/sh \
      -e NGINX_ACTIVE_RELATIVE="${NGINX_ACTIVE_RELATIVE}" \
      -v /etc/nginx:/target \
      postgres:16-alpine \
      -c 'cp "/target/${NGINX_ACTIVE_RELATIVE}.cappers-backup" "/target/${NGINX_ACTIVE_RELATIVE}"'
    echo "nginx config validation failed; the previous config was restored." >&2
    exit 1
  fi
  sudo systemctl reload nginx
fi

if [ "${DEPLOY_PRUNE}" = "1" ]; then
  docker image prune -f
fi

compose ps

# Only this marker represents a successfully applied revision. Keep the previous
# value if building, migrations, service readiness or nginx validation fails.
printf '%s\n' "${target_revision}" > "${deployed_revision_file}.tmp"
mv "${deployed_revision_file}.tmp" "${deployed_revision_file}"
echo "Successfully deployed revision: ${target_revision}"
