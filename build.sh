#!/bin/bash
#
# Baut das CantorHub-Abbild und benennt es nach der Version.
#
#   ./build.sh            Version aus git describe --tags
#   ./build.sh v1.2.3     Version von Hand
#
# git describe liefert auf einem Tag dessen Namen ("v1.0.0") und danach den Tag
# samt Abstand und Commit-Kuerzel ("v1.0.0-7-g7c8b717"). Derselbe String wird
# Abbild-Marke und Versionszeile in der Seitenleiste.

set -e

cd "$(dirname "$0")"

VERSION="${1:-}"
if [ -z "${VERSION}" ]; then
    if ! VERSION="$(git describe --tags --dirty --always 2>/dev/null)"; then
        echo "Kein git-Tag und keine Version angegeben." >&2
        echo "Erst taggen (git tag v1.0.0) oder Version uebergeben: ./build.sh v1.0.0" >&2
        exit 1
    fi
fi

# Eine Abbild-Marke darf kein "+" und kein "~" enthalten; git describe erzeugt
# beides nicht, "-dirty" dagegen schon — das ist zulaessig und bleibt stehen,
# damit ein Bau aus einem unsauberen Arbeitsverzeichnis erkennbar ist.
echo "Baue cantorhub:${VERSION}"

podman build \
    --build-arg "CANTORHUB_VERSION=${VERSION}" \
    -t "cantorhub:${VERSION}" \
    -t "cantorhub:latest" \
    .

echo
echo "Fertig: cantorhub:${VERSION}"
podman images cantorhub
