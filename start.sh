#!/bin/bash

set -e

DEBUG="${DEBUG:-}"
MIGRATE="${MIGRATE:-}"
CANTORHUB_DATA="${CANTORHUB_DATA:-.}"

if [ -n "${DATABASE_URL}" ]; then
    # Kein Echo des Werts: er trägt das Datenbankpasswort.
    echo "Datenbank: ${DATABASE_URL%%:*}"
else
    echo "Datenbank: SQLite unter ${CANTORHUB_DATA}"
fi

mkdir -p "${CANTORHUB_DATA}/media" "${CANTORHUB_DATA}/tiles"

# ==== MIGRATIONSPFAD — faellt nach dem letzten Lauf als Ganzes weg ====
# Einmaliger Import aus dem alten PHP-Portal. Loescht die Datenbank. Siehe
# migration.md; die Quellen liegen unter ${CANTORHUB_DATA}/migration/.
if [ -n "${MIGRATE}" ]; then
    echo "MIGRATE gesetzt — Datenbank wird verworfen und neu aufgebaut."

    if [ -n "${DATABASE_URL}" ]; then
        python manage.py shell -c "
from django.db import connection
with connection.cursor() as c:
    c.execute('SET FOREIGN_KEY_CHECKS = 0')
    c.execute('SHOW TABLES')
    tables = [row[0] for row in c.fetchall()]
    for t in tables:
        c.execute(f'DROP TABLE IF EXISTS {t}')
    c.execute('SET FOREIGN_KEY_CHECKS = 1')
print('Database cleared.')
"
    else
        rm -rf "${CANTORHUB_DATA}/db.sqlite3" "${CANTORHUB_DATA}/media"
        mkdir -p "${CANTORHUB_DATA}/media"
    fi

    # 0002 wird bei jedem Lauf neu erzeugt und nie eingecheckt (siehe CLAUDE.md);
    # 0003 muss dafuer kurz beiseite, sonst haengt es an einer Migration, die es
    # in diesem Moment noch nicht gibt.
    rm -rf intern/migrations/0002_add_filer.py
    mv intern/migrations/0003_import.py /tmp || true

    python manage.py makemigrations intern --name add_filer
    python manage.py migrate

    mv /tmp/0003_import.py intern/migrations || true
    python manage.py import_files --path "${CANTORHUB_DATA}/migration/Avatare"
    python manage.py migrate

    python manage.py createcachetable
    python manage.py index_files &
    # Kein "filer_check --delete-orphans": das Kommando loescht jeden Blob ohne
    # File-Zeile — und genau das ist ein DateiVersion-Blob (importierte Avatar-
    # Fassungen).
    python manage.py thumbnail_files &
fi
# ==== ENDE MIGRATIONSPFAD ====

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

# XMPP nur anfassen, wenn es konfiguriert ist: ohne EJABBERD_HOST/BOT_JID laufen
# beide Kommandos in Verbindungsfehler und fuellen bei jedem Start das Log.
if python manage.py shell -c "
import sys
from intern.app_settings import is_ejabberd_configured
sys.exit(0 if is_ejabberd_configured() else 1)
" >/dev/null 2>&1; then
    python manage.py ejabberd_admin sync
    python manage.py ejabberd_bot &
else
    echo "XMPP nicht konfiguriert (EJABBERD_HOST/EJABBERD_BOT_JID) — Bot bleibt aus."
fi

# Erinnerungen an oeffentliche Auftritte (Auftritts-Mailingliste); Dauerloop wie
# der ejabberd_bot, weil das Projekt keinen Scheduler hat.
python manage.py send_auftritt_erinnerungen --loop &

if [ "${DEBUG}" = "1" ]; then
    python manage.py runserver 0.0.0.0:8001
else
    # Im Container hat collectstatic bereits zur Bauzeit gelaufen; das Ergebnis
    # gehoert zum Abbild. Nur wenn das Manifest fehlt — etwa beim Start aus einem
    # Arbeitsverzeichnis heraus — wird es hier nachgeholt.
    if [ ! -f static/staticfiles.json ]; then
        python manage.py collectstatic --noinput
    fi
    /usr/sbin/nginx -g 'daemon on; master_process on;'
    # exec: gunicorn wird damit selbst zu PID 1 und bekommt das SIGTERM eines
    # "podman stop" direkt. Ohne das bleibt diese Shell PID 1, reicht das Signal
    # nicht weiter, und podman killt den Container nach zehn Sekunden hart —
    # mitten in laufenden Anfragen, bei jedem Deploy.
    # Nur an localhost: nginx laeuft im selben Container und proxied nach
    # 127.0.0.1:8001. Auf 0.0.0.0 waere gunicorn ueber die Podman-Bridge direkt
    # erreichbar — an nginx und damit an realip vorbei, X-Forwarded-* frei setzbar.
    # --threads: kurze Anfragen (media-auth fuer jede Bilddatei, die beiden
    # Polls) warten sonst hinter einem laufenden Seitenaufbau — drei
    # Sync-Prozesse bedienen exakt drei Anfragen gleichzeitig. Der
    # modulweite Zustand des Projekts ist threadsicher: app_settings und
    # apps._migrating sind threading.local.
    exec gunicorn --bind 127.0.0.1:8001 --workers 3 --threads 4 config.wsgi:application
fi
