#!/bin/bash
# Richtet ein Speichergeraet fuer das Backup eines CantorHub-Servers ein
# ("Backup" in INSTALL.md): ein Syncthing-Container, der den Ordner des
# Servers nur empfaengt und jede ersetzte oder geloeschte Datei ein Jahr lang
# aufhebt. Braucht podman oder docker, sonst nichts.
#
#   ./sicherung-speicherseite.sh SERVER-ID [ZIELORDNER] [--verschluesselt]
#   ./sicherung-speicherseite.sh --freigeben NEUE-SERVER-ID
#
# SERVER-ID gibt der Server aus: podman exec cantorhub /app/sicherung-geraet.sh
# Danach nimmt der Server dieses Geraet an — mit --verschluesselt dort mit einem
# Passwort, hier liegen dann nur verschluesselte Dateien.
# --freigeben gibt die vorhandene Sicherung einem neuen Server frei, der aus ihr
# wiederhergestellt wird (die Ersteinrichtung dort zeigt seine ID).

set -e

ABBILD="docker.io/syncthing/syncthing:2"
NAME="cantorhub-sicherung"
ORDNER_ID="cantorhub"
# Staggered Versioning: aeltere Fassungen ein Jahr lang, auch jeder fruehere
# Datenbankstand. Schutz davor, dass ein Loeschen auf dem Server mitwandert.
AUFHEBEN_S=31536000

server_id=""
ziel="${HOME}/cantorhub-sicherung"
typ="receiveonly"
freigeben=""
for arg in "$@"; do
    case "${arg}" in
        --verschluesselt) typ="receiveencrypted" ;;
        --freigeben) freigeben=1 ;;
        -*) echo "Unbekannte Option: ${arg}" >&2; exit 2 ;;
        *) if [ -z "${server_id}" ]; then server_id="${arg}"; else ziel="${arg}"; fi ;;
    esac
done
if [ -z "${server_id}" ]; then
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

if command -v podman >/dev/null; then
    rt=podman
elif command -v docker >/dev/null; then
    rt=docker
else
    echo "Weder podman noch docker gefunden." >&2
    exit 1
fi

# Ohne STGUIADDRESS: mit ihr verlangt die CLI auch den API-Schluessel; ohne
# liest sie beides aus der config.xml.
st() { "${rt}" exec "${NAME}" env -u STGUIADDRESS syncthing cli "$@"; }

if [ -n "${freigeben}" ]; then
    if ! st show system >/dev/null 2>&1; then
        echo "Der Container ${NAME} laeuft hier nicht." >&2
        exit 1
    fi
    # Der neue Server holt sich den Ordner, wie er hier liegt — Typ und
    # Versionierung bleiben; nach dem Einspielen sendet er selbst hierher.
    st config devices add --device-id "${server_id}" --name "CantorHub (neu)"
    st config folders "${ORDNER_ID}" devices add --device-id "${server_id}"
    echo "Freigegeben. Der neue Server sieht dieses Geraet gleich als wartend."
    exit 0
fi

mkdir -p "${ziel}"
# Die Dateien sollen dem aufrufenden Benutzer gehoeren: unter rootless podman
# ist das root im Container (--userns=keep-id vertraegt das Abbild nicht),
# sonst die eigene UID. :Z fuer SELinux. Keine Portfreigabe noetig — Syncthing
# findet den Server ueber Discovery und Relays. Schneller direkt mit
# -p 22000:22000/tcp -p 22000:22000/udp; die Weboberflaeche bleibt zu.
puid="$(id -u)"
pgid="$(id -g)"
if [ "${rt}" = podman ] && [ "$(podman info --format '{{.Host.Security.Rootless}}')" = true ]; then
    puid=0
    pgid=0
fi
# --hostname: Syncthing nennt das Geraet nach ihm — beim Server erscheint so der
# Name dieses Rechners statt einer Container-ID.
"${rt}" run -d --name "${NAME}" --restart unless-stopped \
    --hostname "$(hostname -s 2>/dev/null || echo "${NAME}")" \
    -e PUID="${puid}" -e PGID="${pgid}" -e STNODEFAULTFOLDER=1 \
    -e STGUIADDRESS=127.0.0.1:8384 \
    -v "${ziel}:/var/syncthing:Z" "${ABBILD}" >/dev/null

for _ in $(seq 60); do st show system >/dev/null 2>&1 && break; sleep 2; done

st config devices add --device-id "${server_id}" --name CantorHub
# Typ beim Anlegen: einen bestehenden Ordner stellt syncthing nicht auf
# "verschluesselt" um.
st config folders add --id "${ORDNER_ID}" --label CantorHub \
    --path "/var/syncthing/${ORDNER_ID}" --type "${typ}"
st config folders "${ORDNER_ID}" versioning type set staggered
st config folders "${ORDNER_ID}" versioning params set maxAge "${AUFHEBEN_S}"
st config folders "${ORDNER_ID}" devices add --device-id "${server_id}"

eigene_id=$(st show system | sed -n 's/.*"myID": *"\([^"]*\)".*/\1/p')
echo "Eingerichtet. Die Sicherung landet in ${ziel}/${ORDNER_ID}."
echo
echo "Jetzt auf dem Server annehmen:"
if [ "${typ}" = receiveencrypted ]; then
    echo "  podman exec cantorhub /app/sicherung-geraet.sh ${eigene_id} PASSWORT"
else
    echo "  podman exec cantorhub /app/sicherung-geraet.sh ${eigene_id}"
fi
