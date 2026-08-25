#!/bin/sh
set -e

case "${DEBUG:-False}" in
  True|true|TRUE|1|yes|YES)
    echo "Starting Django development server..."
    exec python manage.py runserver 0.0.0.0:8000
    ;;
  *)
    echo "Collecting static files..."
    python manage.py collectstatic --noinput
    echo "Starting Uvicorn..."
    exec uvicorn cappers.asgi:application \
      --host 0.0.0.0 \
      --port 8000 \
      --workers "${UVICORN_WORKERS:-2}"
    ;;
esac
