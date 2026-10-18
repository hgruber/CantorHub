#!/bin/bash
# Speichergeraete fuer das Backup annehmen, auflisten, entfernen ("Backup" in
# INSTALL.md). Laeuft im Container, neben dem Syncthing aus start.sh:
#
#   podman exec cantorhub /app/sicherung-geraet.sh                 # Stand
#   podman exec cantorhub /app/sicherung-geraet.sh ID              # annehmen
#   podman exec cantorhub /app/sicherung-geraet.sh ID PASSWORT     # verschluesselt
#   podman exec cantorhub /app/sicherung-geraet.sh --entfernen ID
#
# Verschluesselt heisst: das Geraet bekommt nur verschluesselte Dateien und
# kann sie ohne das Passwort nicht lesen — fuer ein Geraet, dem man die Daten
# der Mitglieder nicht anvertrauen will. Das Passwort gut aufheben: ohne es
# ist die Sicherung wertlos.

set -e

ST_HOME="${CANTORHUB_DATA:-/data}/syncthing"
st() { syncthing cli --home="${ST_HOME}" "$@"; }

if ! st show system >/dev/null 2>&1; then
    echo "Syncthing laeuft nicht (oder startet noch)." >&2
    exit 1
fi

if [ "$1" = "--entfernen" ] && [ -n "$2" ]; then
    st config devices "$2" delete
    echo "Geraet $2 entfernt."
    exit 0
fi

if [ -n "$1" ]; then
    if [ -n "$2" ]; then
        st config devices add --device-id "$1" --name Sicherung --untrusted
        st config folders cantorhub devices add --device-id "$1" \
            --encryption-password "$2"
        echo "Geraet $1 angenommen, verschluesselt."
    else
        st config devices add --device-id "$1" --name Sicherung
        st config folders cantorhub devices add --device-id "$1"
        echo "Geraet $1 angenommen."
    fi
    exit 0
fi

eigene_id=$(st show system | python -c 'import json, sys; print(json.load(sys.stdin)["myID"])')
echo "Geraete-ID dieses Servers: ${eigene_id}"
echo
echo "Wartende Geraete (mit ID annehmen):"
st show pending devices | python -c '
import json, sys
wartend = json.load(sys.stdin)
for geraet_id, info in wartend.items():
    print("  " + geraet_id + "  " + info.get("name", "") + "  " + info.get("address", ""))
if not wartend:
    print("  keine")
'
echo
echo "Angenommene Geraete:"
verbindungen=$(st show connections)
st config folders cantorhub devices list | grep -vx "${eigene_id}" | while read -r geraet_id; do
    verbunden=$(echo "${verbindungen}" | python -c "
import json, sys
print('verbunden' if json.load(sys.stdin)['connections'].get('${geraet_id}', {}).get('connected') else 'getrennt')
")
    echo "  ${geraet_id}  ${verbunden}"
done
