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

# Tabelle fuer den DatabaseCache (CACHES in settings.py) — traegt die beiden
# IP-Drosseln. Reines DDL, keine Migration, und idempotent: existiert sie
# bereits, meldet das Kommando das nur.
python manage.py createcachetable

# Datenschutz: Änderungsprotokoll nach Ablauf der Aufbewahrungsfrist (3 Jahre) löschen.
python manage.py cleanup_changelog &

# Alte Dateifassungen (überschriebene Uploads) nach Frist bzw. Anzahl abräumen.
# Grosszuegige Werte, damit die aus Avatare/ importierten historischen Fassungen
# (2012 ff.) nicht beim naechsten Serverstart wieder verschwinden.
python manage.py cleanup_dateiversionen --days 36500 --keep 25 &

python manage.py ejabberd_admin sync
python manage.py ejabberd_bot &

# Erinnerungen an oeffentliche Auftritte (Auftritts-Mailingliste); Dauerloop wie
# der ejabberd_bot, weil das Projekt keinen Scheduler hat.
python manage.py send_auftritt_erinnerungen --loop &

if [ "${DEBUG}" = "1" ]; then
    python manage.py runserver 0.0.0.0:8001
else
    python manage.py collectstatic --noinput
    /usr/sbin/nginx -g 'daemon on; master_process on;'
    # Nur an localhost: nginx laeuft im selben Container und proxied nach
    # 127.0.0.1:8001. Auf 0.0.0.0 waere gunicorn ueber die Podman-Bridge direkt
    # erreichbar — an nginx und damit an realip vorbei, X-Forwarded-* frei setzbar.
    gunicorn --bind 127.0.0.1:8001 --workers 3 config.wsgi:application
fi
