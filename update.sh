#!/bin/bash
#
# update-Hook des Bare-Repos auf dem Server
# (/root/podman/CantorHub.git/hooks/update).
#
# Ein Versions-Tag ist die Freigabe — post-receive baut auf es hin ein Abbild.
# Dieser Hook laesst so ein Tag nur durch, wenn der getaggte Commit in
# CHANGELOG.md einen gefuellten Abschnitt fuer genau diese Version traegt. Ohne
# ihn ginge eine Fassung in Betrieb, von der niemand mehr nachlesen kann, was
# sich geaendert hat.
#
# Streng gilt das fuer Endfassungen. Eine Vorabversion (v1.0.0-rc2) darf sich
# auch auf den Abschnitt ihrer Endfassung oder auf die Sammlung
# "## Unveroeffentlicht" stuetzen — in der rc-Phase wird oft getaggt, und wer
# jeden Zwischenstand einzeln beschreiben muss, beschreibt am Ende gar nichts.
#
# Warum update und nicht pre-receive: pre-receive laeuft einmal fuer den ganzen
# Push und kennt nur alles oder nichts. update laeuft je Ref, also landet master
# und nur das Tag wird verweigert — und ohne Tag baut post-receive nicht. Die
# Arbeit haengt damit nicht am Changelog, die Auslieferung schon.
#
# Installation:
#   scp update.sh root@server:/root/podman/CantorHub.git/hooks/update
#   ssh root@server chmod +x /root/podman/CantorHub.git/hooks/update
#
# ACHTUNG, hier anders als in post-receive: GIT_OBJECT_DIRECTORY,
# GIT_QUARANTINE_PATH und Verwandte bleiben stehen. Die gerade empfangenen
# Objekte liegen noch in der Quarantaene; ohne diese Variablen ist der neue
# Commit unlesbar und der Hook wuerde jedes Tag ablehnen. post-receive wirft sie
# weg, weil es in einem anderen Verzeichnis baut — das nicht "vereinheitlichen".
#
# Der Exit-Status entscheidet ueber genau dieses Ref: 0 laesst es durch, alles
# andere lehnt es ab. Die Ausgabe erreicht den Pushenden mit "remote:" davor.
#
# Notausgang: die Marke [ohne-changelog] in der Nachricht eines annotierten
# Tags. Sie bleibt im Tag nachlesbar — ein uebergangener Changelog steht damit
# dort, wo man spaeter nach der Freigabe sieht.
#
# "git push -o changelog=skip" waere der bequemere Weg und ist unten mit
# vorgesehen, wirkt aber nicht: githooks(5) sichert Push-Optionen nur
# pre-receive und post-receive zu, und gemessen (git 2.55, mit
# receive.advertisePushOptions=true) kommen sie im update-Hook wirklich nicht
# an — GIT_PUSH_OPTION_COUNT ist hier nicht gesetzt. Der Zweig bleibt stehen,
# damit er greift, sobald git sie durchreicht; verlassen kann man sich nur auf
# die Tagmarke.

set -uo pipefail

# ---------------------------------------------------------------- Einstellungen

# Dasselbe Muster, das post-receive fuer baubare Tags anlegt. Was nicht darauf
# passt, wird dort nicht gebaut und geht diesen Hook nichts an.
readonly TAG_MUSTER='^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$'

readonly DATEI='CHANGELOG.md'

# Die Sammelueberschrift. Der Umlaut steht hier, weil der Wert wortwoertlich mit
# der Ueberschrift in der Datei uebereinstimmen muss — Kommentare bleiben ASCII.
readonly SAMMELT='Unveröffentlicht'

readonly NOTAUSGANG='changelog=skip'
readonly TAGMARKE='[ohne-changelog]'
readonly PROTOKOLL='/var/log/cantorhub-build.log'

readonly NULLREV='^0+$'

refname="${1:-}"
newrev="${3:-}"

# ------------------------------------------------------------------- Werkzeuge

# An den Pushenden, sonst nichts: die Anleitung unten waere im Protokoll nur
# Rauschen. Aufgezeichnet werden allein Abweisung und Notausgang.
melde() { echo "$*"; }

# Die Reihenfolge der Umleitungen ist hier nicht beliebig: bash oeffnet sie von
# links nach rechts, und ein ">>" auf eine unbeschreibbare Datei meldet das auf
# das stderr, das zu diesem Zeitpunkt noch offen ist. Erst also stderr
# stilllegen, dann anhaengen — sonst stehen im Push-Output so viele
# "Keine Berechtigung" wie Protokollzeilen.
protokolliere() {
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" 2>/dev/null >>"${PROTOKOLL}" || true
}

fehler() {
    melde "FEHLER: $*"
    protokolliere "FEHLER: $*"
}

# Eine Ablehnung nennt den Weg heraus. Wer das hier abends vor einem Auftritt
# liest, soll nicht erst im Skript nachsehen muessen, was gemeint ist.
abweisung() {
    local tag="$1" grund="$2"
    fehler "Tag ${tag} abgewiesen: ${grund}."
    melde ""
    melde "Ausgeliefert wird nur, was in ${DATEI} steht. Dort fehlt:"
    melde ""
    melde "    ## ${tag} — $(date '+%Y-%m-%d')"
    melde ""
    melde "    - was sich geaendert hat"
    melde ""
    if [ "${tag}" != "${tag%%-*}" ]; then
        melde "Fuer eine Vorabversion genuegt auch ein gefuellter Abschnitt \"## ${tag%%-*}\""
        melde "oder \"## ${SAMMELT}\" — dort sammelt sich, was noch kein Tag hat."
        melde ""
    fi
    melde "Nachtragen, committen, Tag daraufsetzen, neu pushen:"
    melde ""
    melde "    git tag -f -a ${tag} -m \"Release ${tag#v}\""
    melde "    git push origin master"
    melde "    git push --force origin ${tag}"
    melde ""
    melde "Im Notfall laesst die Marke ${TAGMARKE} in der Tagnachricht das Tag durch:"
    melde ""
    melde "    git tag -f -a ${tag} -m \"Release ${tag#v} ${TAGMARKE}\""
    exit 1
}

# Push-Option gesetzt? receive-pack legt sie als GIT_PUSH_OPTION_<n> ab — in
# diesem Hook bisher nicht, siehe Kopf. Bleibt fuer den Tag stehen, an dem es
# soweit ist.
notausgang_gesetzt() {
    local anzahl="${GIT_PUSH_OPTION_COUNT:-0}" i name
    for (( i = 0; i < anzahl; i++ )); do
        name="GIT_PUSH_OPTION_${i}"
        [ "${!name-}" = "${NOTAUSGANG}" ] && return 0
    done
    return 1
}

# Marke in der Nachricht eines annotierten Tags — der Weg, der unabhaengig von
# der git-Fassung des Servers funktioniert und im Tag nachlesbar bleibt.
tagmarke_gesetzt() {
    [ "$(git cat-file -t "${newrev}" 2>/dev/null)" = "tag" ] || return 1
    git cat-file tag "${newrev}" 2>/dev/null | grep -qF "${TAGMARKE}"
}

# Traegt ${inhalt} einen Abschnitt "## <kopf>" mit mindestens einem Stichpunkt?
#   0 = ja, 1 = Ueberschrift da, aber ohne Stichpunkt, 2 = keine solche Ueberschrift
#
# Verglichen wird das zweite Feld der Ueberschriftzeile ("## v1.0.1 — 2026-09-21"
# ergibt "v1.0.1"): kein Maskieren der Punkte, kein Zweifel an der Abgrenzung.
# Eine "###"-Zeile beendet den Abschnitt nicht, sie gehoert hinein. Exit 3 aus awk
# heisst: gar keine solche Ueberschrift.
abschnitt_gefuellt() {
    local kopf="$1" abschnitt
    abschnitt="$(awk -v kopf="${kopf}" '
        /^##[[:space:]]/ { drin = ($2 == kopf); if (drin) gefunden = 1; next }
        drin
        END { if (!gefunden) exit 3 }
    ' <<<"${inhalt}")"
    [ $? -eq 3 ] && return 2
    grep -Eq '^[[:space:]]*[-*][[:space:]]+[^[:space:]]' <<<"${abschnitt}" || return 1
    return 0
}

# --------------------------------------------------------------------- Ablauf

# Nur Versions-Tags. Zweige, fremde Tagnamen und Loeschungen laufen durch.
case "${refname}" in
    refs/tags/*) ;;
    *) exit 0 ;;
esac

tag="${refname#refs/tags/}"
[[ "${tag}" =~ ${TAG_MUSTER} ]] || exit 0
[[ "${newrev}" =~ ${NULLREV} ]] && exit 0

uebergehen() {
    melde "Changelog-Sperre fuer ${tag} uebergangen ($1)."
    protokolliere "Changelog-Sperre fuer ${tag} uebergangen ($1)."
    exit 0
}

notausgang_gesetzt && uebergehen "push -o ${NOTAUSGANG}"
tagmarke_gesetzt   && uebergehen "${TAGMARKE} in der Tagnachricht"

commit="$(git rev-parse --verify --quiet "${newrev}^{commit}")" \
    || abweisung "${tag}" "zeigt auf kein Commit"

git cat-file -e "${commit}:${DATEI}" 2>/dev/null \
    || abweisung "${tag}" "${DATEI} fehlt in diesem Commit"

inhalt="$(git cat-file -p "${commit}:${DATEI}" 2>/dev/null)" \
    || abweisung "${tag}" "${DATEI} liess sich nicht lesen"

# Welche Ueberschrift darf dieses Tag tragen? Eine Endfassung nur ihre eigene —
# sie ist die Schranke, die zaehlt. Eine Vorabversion darf sich auch auf den
# Abschnitt ihrer Endfassung oder auf die Sammlung stuetzen: in der rc-Phase wird
# oft getaggt, und die Zwischenstaende liest hinterher niemand.
endfassung="${tag%%-*}"
kandidaten=("${tag}")
if [ "${tag}" != "${endfassung}" ]; then
    kandidaten+=("${endfassung}" "${SAMMELT}")
    erwartet="\"## ${tag}\", \"## ${endfassung}\" oder \"## ${SAMMELT}\""
else
    erwartet="\"## ${tag}\""
fi

# Ein leerer Abschnitt ist etwas anderes als ein fehlender; die Meldung soll das
# nicht verwischen. Trifft beides zu, wiegt der leere schwerer — dort hat jemand
# angefangen und den Inhalt vergessen.
leer=0
for kopf in "${kandidaten[@]}"; do
    abschnitt_gefuellt "${kopf}"
    case $? in
        0) exit 0 ;;
        1) leer=1 ;;
    esac
done

if [ "${leer}" -eq 1 ]; then
    abweisung "${tag}" "der Abschnitt ${erwartet} in ${DATEI} ist leer"
else
    abweisung "${tag}" "in ${DATEI} steht kein Abschnitt ${erwartet}"
fi
