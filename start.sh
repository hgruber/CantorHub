#!/bin/bash

set -e

DEBUG="${DEBUG:-}"
CANTORHUB_DATA="${CANTORHUB_DATA:-.}"

if [ -n "${DATABASE_URL}" ]; then
    # Kein Echo des Werts: er trägt das Datenbankpasswort.
    echo "Datenbank: ${DATABASE_URL%%:*}"
else
    echo "Datenbank: SQLite unter ${CANTORHUB_DATA}"
fi

mkdir -p "${CANTORHUB_DATA}/media" "${CANTORHUB_DATA}/tiles"

# Die eigene Startseite: fehlt der Ordner, kommt die mitgelieferte Demo als
# Kopie hinein — zum Ueberschreiben mit eigenen Dateien. Ein vorhandener Ordner
# (auch ein leerer oder ein git-Checkout) bleibt unangetastet; was darin fehlt,
# liefert weiterhin intern/startseite (docs/startseite.md).
if [ ! -e "${CANTORHUB_DATA}/startseite" ]; then
    cp -R intern/startseite "${CANTORHUB_DATA}/startseite"
    echo "Startseite: Demo nach ${CANTORHUB_DATA}/startseite kopiert."
fi

# Bringt die Datenbank auf den Stand des Abbilds: jede eingecheckte Migration
# unter intern/migrations/, die noch nicht verbucht ist, laeuft hier — bei jedem
# Start, eine schon angewendete ist ein No-op. set -e: scheitert eine, startet
# der Container nicht, statt mit halbem Schema zu laufen.
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

# Haelt einen Dauerprozess am Leben: endet er mit Fehler (Ausnahme, Signal wie
# ein OOM-Kill), startet er nach 30 s neu. Ein Ende mit 0 ist gewollt und bleibt
# dabei. Der Bot nutzt das fuer neue Zugangsdaten: er endet mit Code 3, sobald
# sie sich in der Konfiguration aendern, und kommt hier mit ihnen wieder hoch.
neustart_bei_absturz() {
    local code
    while true; do
        "$@" && return 0
        code=$?
        echo "$* beendet mit Code ${code} — Neustart in 30 s." >&2
        sleep 30
    done
}

# Der Abgleich nur, wenn XMPP konfiguriert ist: ohne EJABBERD_HOST/BOT_JID liefe
# er in Verbindungsfehler und fuellte bei jedem Start das Log. Der Bot startet
# immer — ohne Konfiguration wartet er darauf und holt den Abgleich selbst nach.
# Der ganze Block laeuft im Hintergrund, damit das Portal nicht auf den Abgleich
# wartet; darin nacheinander, weil der Bot das Konto braucht, das sync anlegt.
# Forenbeitraege aus der Zwischenzeit gehen nicht verloren: der Bot fuehrt seinen
# Relay-Stand in einer Datei unter CANTORHUB_DATA und holt sie nach.
(
    if python manage.py shell -c "
import sys
from intern.app_settings import is_ejabberd_configured
sys.exit(0 if is_ejabberd_configured() else 1)
" >/dev/null 2>&1; then
        python manage.py ejabberd_admin sync \
            || echo "ejabberd_admin sync fehlgeschlagen — Bot startet trotzdem."
    else
        echo "XMPP nicht konfiguriert — Bot wartet auf die Zugangsdaten (/intern/konfiguration/)."
    fi
    neustart_bei_absturz python manage.py ejabberd_bot
) &

# Erinnerungen an oeffentliche Auftritte (Auftritts-Mailingliste); Dauerloop wie
# der ejabberd_bot, weil das Projekt keinen Scheduler hat.
neustart_bei_absturz python manage.py send_auftritt_erinnerungen --loop &

# Backup: der Datenbankstand als SQLite-Datei nach sicherung/ im
# Datenverzeichnis, alle SICHERUNG_STUNDEN (Konfiguration, 0 = aus). Danach ist
# das Datenverzeichnis allein das ganze Backup ("Backup" in INSTALL.md).
neustart_bei_absturz python manage.py sicherung --loop &

# Syncthing spiegelt das Datenverzeichnis auf die Geraete, die der Betreiber
# mit sicherung-geraet.sh annimmt; solange keines angenommen ist, teilt es
# nichts. Nur im Container: in der Entwicklung ist das Datenverzeichnis der
# Checkout selbst.
if [ "${DEBUG}" != "1" ] && command -v syncthing >/dev/null; then
    ST_HOME="${CANTORHUB_DATA}/syncthing"
    # Was nicht mitgeht. Nur angelegt, wenn sie fehlt — eigene Zeilen bleiben.
    if [ ! -e "${CANTORHUB_DATA}/.stignore" ]; then
        cat > "${CANTORHUB_DATA}/.stignore" <<'EOF'
// Angelegt von start.sh; eigene Zeilen duerfen dazu.
// Schluessel und Zertifikat dieses Servers:
/syncthing
// Kachelcache, jederzeit neu ladbar:
/tiles
// Eine laufende SQLite-Datenbank; ihre konsistente Kopie liegt in sicherung/:
/db.sqlite3
/db.sqlite3-*
// Halbfertige Sicherungen:
/sicherung/*.tmp*
// Quellen des einmaligen Altdaten-Imports:
/migration
EOF
    fi
    if [ ! -f "${ST_HOME}/config.xml" ]; then
        syncthing generate --home="${ST_HOME}" --no-default-folder \
            --skip-port-probing >/dev/null
    fi
    # Ohne neustart_bei_absturz: syncthing hat einen eigenen Waechter, der es
    # nach einem Absturz und nach Konfigurationsaenderungen neu startet.
    syncthing serve --home="${ST_HOME}" --no-browser --no-upgrade &
    (
        st() { syncthing cli --home="${ST_HOME}" "$@"; }
        for _ in $(seq 60); do st show system >/dev/null 2>&1 && break; sleep 2; done
        # sendonly: nichts, was auf einem Speichergeraet geschieht, wirkt zurueck.
        # Den Typ nimmt syncthing nur beim Anlegen zuverlaessig an.
        if ! st config folders list | grep -qx cantorhub; then
            st config folders add --id cantorhub --label CantorHub \
                --path "${CANTORHUB_DATA}" --type sendonly
        fi
        echo "Syncthing: Geraete-ID $(st show system \
            | python -c 'import json, sys; print(json.load(sys.stdin)["myID"])')"
    ) &
fi

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
