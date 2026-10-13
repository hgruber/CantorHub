#!/bin/bash
#
# post-receive-Hook des Bare-Repos auf dem Server
# (/root/podman/CantorHub.git/hooks/post-receive).
#
# Frueher stand hier ein "systemctl restart": der Code lag als Arbeitskopie im
# Volume cantorhub:/app, ein "git pull" davor genuegte. Seit der Code im Abbild
# steckt — samt collectstatic und den Migrationen, die start.sh beim Start
# anwendet — muss ein Push stattdessen ein Abbild bauen.
#
# Gebaut wird ausschliesslich auf einen gueltigen Versions-Tag hin. Ein Push auf
# master aendert am Betrieb nichts mehr; erst das Tag macht eine Fassung zur
# Auslieferung.
#
# Installation:
#   scp post-receive.sh root@server:/root/podman/CantorHub.git/hooks/post-receive
#   ssh root@server chmod +x /root/podman/CantorHub.git/hooks/post-receive
#
# Der Exit-Status eines post-receive-Hooks beeinflusst den Push nicht mehr — die
# Refs stehen bereits. Die Ausgabe dagegen laeuft dem Pushenden mit "remote:"
# davor ueber den Bildschirm, und dort soll jeder Fehler sichtbar werden.

set -uo pipefail

# ---------------------------------------------------------------- Einstellungen

# Erlaubte Tagnamen: v1.2.3, optional mit Vorabkennung (v1.0.0-rc1).
readonly TAG_MUSTER='^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$'

# Nur Tags, die auf diesem Zweig liegen, sind auslieferbar.
readonly ZWEIG='refs/heads/master'

readonly ABBILD='cantorhub'

# Ob eine Vorabversion die Marke :latest mitnimmt, entscheidet nicht mehr ein
# Schalter, sondern der Zustand des Repos — siehe endfassung_existiert().

# Aeltere Versionsabbilder abraeumen, sobald mehr als so viele liegen. Auf dem
# Server sind keine 10 GB frei; jedes Abbild kostet einige hundert MB.
readonly BEHALTE=3

# Mindestens so viel freier Platz (MB) unter /var/lib/containers, sonst wird
# gar nicht erst gebaut: ein auf halber Strecke verhungernder Bau hinterlaesst
# Schichten, die niemand zuordnen kann.
readonly PLATZ_MB=4000

# Dienst nach erfolgreichem Bau neu starten? Erst einschalten, wenn
# container-cantorhub.service umgestellt ist — solange die Unit noch
# "--volume=cantorhub:/app" und "/app/migrate.sh" traegt, ueberdeckt die alte
# Arbeitskopie im Volume genau den Code, den das neue Abbild mitbringt.
readonly NEUSTART=0
readonly DIENST='container-cantorhub.service'

readonly PROTOKOLL='/var/log/cantorhub-build.log'

# ------------------------------------------------------------------- Werkzeuge

# Der Hook erbt GIT_DIR und Verwandte. Sie zeigen auf das Bare-Repo und wuerden
# jedes git in einem anderen Verzeichnis — etwa im Bauverzeichnis — dorthin
# umbiegen. Also den Pfad einmal festhalten und die Variablen danach loswerden.
REPO="$(git rev-parse --absolute-git-dir)" || exit 1
readonly REPO
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_QUARANTINE_PATH \
      GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES

git_() { git --git-dir="${REPO}" "$@"; }

melde() {
    local zeile="$*"
    echo "${zeile}"
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${zeile}" >>"${PROTOKOLL}" 2>/dev/null || true
}

fehler() { melde "FEHLER: $*"; }

# ------------------------------------------------------------------ Pruefungen

# Gibt 0 zurueck, wenn aus diesem Ref ein Abbild werden soll. Jede Ablehnung
# nennt ihren Grund — ein stiller Hook auf einen vertippten Tagnamen hin ist
# das, was man am Abend vor dem Auftritt am wenigsten brauchen kann.
tag_gueltig() {
    local refname="$1" newrev="$2" tag="$3"

    if [ "${newrev}" = "0000000000000000000000000000000000000000" ]; then
        melde "Tag ${tag} geloescht — nichts zu bauen."
        return 1
    fi

    if ! [[ "${tag}" =~ ${TAG_MUSTER} ]]; then
        fehler "Tagname ${tag} passt nicht auf v<major>.<minor>.<patch>[-vorab] — kein Bau."
        return 1
    fi

    local commit
    commit="$(git_ rev-parse --verify --quiet "${refname}^{commit}")" || {
        fehler "${tag} zeigt auf kein Commit — kein Bau."
        return 1
    }

    # Annotiert oder nicht ist beides zulaessig (v1.0.0-rc1 ist es nicht),
    # aber ein annotiertes Tag traegt Datum und Autor der Freigabe.
    if [ "$(git_ cat-file -t "${refname}" 2>/dev/null)" != "tag" ]; then
        melde "Hinweis: ${tag} ist ein einfaches Tag; 'git tag -a' haelt fest, wer wann freigegeben hat."
    fi

    if ! git_ rev-parse --verify --quiet "${ZWEIG}" >/dev/null; then
        fehler "${ZWEIG} existiert im Repo nicht — kein Bau."
        return 1
    fi

    # Das Tag muss auf dem ausgelieferten Zweig liegen. Ein Tag auf einem
    # Seitenast waere sonst ein Abbild, zu dem es keinen Verlauf gibt.
    if ! git_ merge-base --is-ancestor "${commit}" "${ZWEIG}"; then
        fehler "${tag} liegt nicht auf ${ZWEIG#refs/heads/} — kein Bau."
        return 1
    fi

    return 0
}

# Liegt im Repo schon eine Endfassung? Daran haengt, ob eine Vorabversion die
# Marke :latest mitnimmt. In der rc-Phase soll sie das — sonst hat ein rc-Tag
# keine Wirkung, weil der Dienst :latest startet. Sobald die erste Endfassung
# getaggt ist, gehoert :latest den Endfassungen: ein spaeteres v1.1.0-rc1 darf
# den Betrieb nicht mehr mitziehen.
#
# Gefragt wird nach Tags, nicht nach Abbildern — raeume_auf loescht alte
# Abbilder, ein Tag bleibt. Frueher stand hier ein Schalter, der nach der 1.0.0
# von Hand umzulegen war; genau die Art Schalter, die man vergisst.
endfassung_existiert() {
    git_ tag --list 'v[0-9]*' | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'
}

platz_reicht() {
    local frei
    frei="$(df -Pm /var/lib/containers 2>/dev/null | awk 'NR==2 {print $4}')"
    [ -z "${frei}" ] && return 0     # Kein Urteil moeglich: dann nicht im Weg stehen.
    if [ "${frei}" -lt "${PLATZ_MB}" ]; then
        fehler "Nur ${frei} MB frei unter /var/lib/containers, noetig sind ${PLATZ_MB} MB."
        fehler "Erst aufraeumen (podman image prune -a), dann Tag neu pushen."
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------- Bauen

baue() {
    local tag="$1"
    local bauverzeichnis
    bauverzeichnis="$(mktemp -d /var/tmp/cantorhub-bau.XXXXXX)" || return 1
    trap 'rm -rf "${bauverzeichnis}"' RETURN

    # git archive statt Arbeitskopie: was im Abbild landet, steht damit genau im
    # Tag und nicht in irgendeinem Zustand eines Verzeichnisses auf dem Server.
    if ! git_ archive --format=tar "${tag}" | tar -x -C "${bauverzeichnis}"; then
        fehler "Konnte ${tag} nicht auspacken."
        return 1
    fi

    # Dieselben Marken, die build.sh setzt — der Hook baut aber selbst, weil er
    # ueber :latest entscheidet (siehe endfassung_existiert) und build.sh sie
    # bedingungslos vergibt.
    local marken=(-t "${ABBILD}:${tag}")
    if [[ "${tag}" != *-* ]]; then
        marken+=(-t "${ABBILD}:latest")
    elif endfassung_existiert; then
        melde "Vorabversion, und eine Endfassung gibt es schon: ${ABBILD}:latest bleibt, wo es ist."
    else
        melde "Vorabversion vor der ersten Endfassung: ${ABBILD}:latest folgt ihr."
        marken+=(-t "${ABBILD}:latest")
    fi

    melde "Baue ${ABBILD}:${tag} …"
    podman build \
        --build-arg "CANTORHUB_VERSION=${tag}" \
        "${marken[@]}" \
        "${bauverzeichnis}" 2>&1 | tee -a "${PROTOKOLL}"
    # tee verdeckt den Status von podman; PIPESTATUS[0] ist der echte.
    if [ "${PIPESTATUS[0]}" -ne 0 ]; then
        fehler "Bau von ${tag} fehlgeschlagen — das laufende Abbild bleibt unberuehrt."
        return 1
    fi

    melde "Fertig: ${ABBILD}:${tag}"
    return 0
}

# Alte Versionsabbilder abraeumen, die hoechsten ${BEHALTE} bleiben. :latest und
# alles, woran ein Container haengt, fasst podman von sich aus nicht an —
# deshalb genuegt hier das schlichte rmi mit unterdruecktem Fehler.
raeume_auf() {
    # Sortiert wird nach Version, nicht nach Bauzeit: ein nachtraeglich
    # wiederholter Bau einer alten Fassung soll nicht die juengste verdraengen.
    # Die Tilde wieder als Kunstgriff fuer die Vorabversionen (siehe unten).
    local alt
    alt="$(podman images --filter "reference=${ABBILD}" \
              --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
           | grep -E ':v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$' \
           | awk -F: '{ v = $2; sub(/-/, "~", v); print v "\t" $0 }' \
           | sort -V \
           | head -n "-${BEHALTE}" \
           | cut -f2)"
    local marke
    for marke in ${alt}; do
        if podman rmi "${marke}" >/dev/null 2>&1; then
            melde "Altes Abbild entfernt: ${marke}"
        fi
    done
    # Die von der neuen Marke verdraengte alte :latest-Schicht haengt jetzt
    # namenlos herum und kostet Platz.
    podman image prune -f >/dev/null 2>&1 || true
}

# --------------------------------------------------------------------- Ablauf

# Mehrere Tags in einem Push (nachgereichte alte Tags etwa) ergeben nicht
# mehrere Abbilder: gebaut wird der hoechste gueltige.
kandidaten=()
while read -r _oldrev newrev refname; do
    case "${refname}" in
        refs/tags/*) ;;
        refs/heads/*)
            melde "${refname#refs/heads/} empfangen — die Auslieferung haengt am Tag, nicht am Zweig."
            continue
            ;;
        *) continue ;;
    esac

    tag="${refname#refs/tags/}"
    if tag_gueltig "${refname}" "${newrev}" "${tag}"; then
        kandidaten+=("${tag}")
    fi
done

[ "${#kandidaten[@]}" -eq 0 ] && exit 0

# sort -V stellt v1.0.0 vor v1.0.0-rc1 — eine Vorabversion gaelte damit als die
# hoehere. Eine Tilde an der Stelle des trennenden Bindestrichs dreht das um:
# "~" sortiert dort vor allem anderen, wie es dpkg vormacht.
tag="$(printf '%s\n' "${kandidaten[@]}" | sed 's/-/~/' | sort -V | sed 's/~/-/' | tail -1)"
if [ "${#kandidaten[@]}" -gt 1 ]; then
    melde "Mehrere Tags empfangen, gebaut wird ${tag}."
fi

if podman image exists "${ABBILD}:${tag}" 2>/dev/null; then
    melde "Hinweis: ${ABBILD}:${tag} existiert bereits und wird ueberschrieben."
fi

platz_reicht || exit 1
baue "${tag}" || exit 1
raeume_auf

if [ "${NEUSTART}" -eq 1 ]; then
    melde "Starte ${DIENST} neu …"
    if systemctl restart "${DIENST}"; then
        melde "${DIENST} laeuft auf ${ABBILD}:${tag}."
    else
        fehler "Neustart von ${DIENST} fehlgeschlagen — 'journalctl -u ${DIENST}' zeigt, warum."
        exit 1
    fi
else
    melde "Abbild steht. Uebernehmen mit: systemctl restart ${DIENST}"
fi

exit 0
