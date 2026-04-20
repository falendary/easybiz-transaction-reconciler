#!/bin/bash
set -e

echo "→ Waiting for database…"
until python manage.py check --database default > /dev/null 2>&1; do
  sleep 1
done

echo "→ Running migrations…"
python manage.py migrate --noinput

echo "→ Creating superuser (skipped if already exists)…"
python manage.py createsuperuser --noinput 2>/dev/null || true

echo "→ Starting server…"
exec python manage.py runserver 0.0.0.0:8000
