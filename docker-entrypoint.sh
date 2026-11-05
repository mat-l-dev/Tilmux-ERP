#!/bin/sh
set -e

# Las migraciones son idempotentes: se aplican al arrancar.
uv run --no-dev python manage.py migrate --noinput

exec "$@"
