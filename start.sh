#!/bin/bash

set -e

DEBUG="${DEBUG:-}"
DB_HOST="${DB_HOST:-}"

if [ -n "$DB_HOST" ]; then
    echo "Detected DB_HOST=$DB_HOST; using MySQL."
else
    echo "No DB_HOST set; using SQLite."
fi

python manage.py migrate

# Datenschutz: Änderungsprotokoll nach Ablauf der Aufbewahrungsfrist (3 Jahre) löschen.
python manage.py cleanup_changelog &

# Alte Dateifassungen (überschriebene Uploads) nach Frist bzw. Anzahl abräumen.
# Grosszuegige Werte, damit die aus Avatare/ importierten historischen Fassungen
# (2012 ff.) nicht beim naechsten Serverstart wieder verschwinden.
python manage.py cleanup_dateiversionen --days 36500 --keep 25 &

python manage.py ejabberd_admin sync
python manage.py ejabberd_bot &

if [ "${DEBUG}" = "1" ]; then
    python manage.py runserver 0.0.0.0:8001
else
    python manage.py collectstatic --noinput
    /usr/sbin/nginx -g 'daemon on; master_process on;'
    gunicorn --bind 0.0.0.0:8001 --workers 3 config.wsgi:application
fi
