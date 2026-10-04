#!/bin/bash
#
# Erste Runde nach der Migration: die Gruendungsmitglieder bestaetigen ihre Daten,
# alle uebrigen Altkonten bekommen den Link zum Mitgliedsantrag.
#
#   ./Initial_Einladungen.sh            Probelauf: zeigt nur, wer was bekaeme
#   ./Initial_Einladungen.sh --senden   verschickt nach Rueckfrage
#
# Gruendungsmitglieder = Gruppe "Gründer" mit Tag "Mitglied", aktiv, mit E-Mail.
#   -> send_reconfirmation --user: Mail MAIL_BESTAETIGUNG, Zugang bis zur
#      Bestaetigung gesperrt.
# Uebrige = inaktiv, ohne Tag "Mitglied", kein Namensverweis, nicht anonymisiert,
#   mit E-Mail.
#   -> send_antragslink --user: Mail MAIL_EINLADUNG mit vorausgefuelltem Antrag;
#      Konto bleibt inaktiv bis "Mitgliedschaft genehmigen".
#
# Nur EINMAL senden. Ein zweiter Lauf schriebe die Gruender erneut an, die
# inzwischen bestaetigt haben (sie sind dann wieder aktiv), und schickte den
# Uebrigen, die noch nicht genehmigt sind, einen weiteren Antragslink.
#
# Aufruf der Django-Kommandos: standardmaessig im Container "cantorhub".
#   CONTAINER=anderer ./Initial_Einladungen.sh       anderer Containername
#   MANAGE="python manage.py" ./Initial_Einladungen.sh   ohne Container (Entwicklung)

set -e
set -o pipefail

CONTAINER="${CONTAINER:-cantorhub}"
if [ -n "${MANAGE:-}" ]; then
    read -r -a MANAGE_CMD <<< "${MANAGE}"
else
    MANAGE_CMD=(podman exec "${CONTAINER}" python manage.py)
fi

SENDEN=0
case "${1:-}" in
    "")       ;;
    --senden) SENDEN=1 ;;
    *)        echo "Aufruf: $0 [--senden]" >&2; exit 2 ;;
esac

manage() {
    "${MANAGE_CMD[@]}" "$@"
}

# Benutzernamen einer Auswahl, einer pro Zeile. Die Zeilen tragen ein Praefix,
# damit Log- und Warnzeilen aus dem Django-Start nicht mitgelesen werden;
# Benutzernamen duerfen Leerzeichen enthalten.
liste() {
    manage shell -c "
from django.db.models import Q
from intern.models import NAMENSVERWEIS, User
ohne_mail = Q(email__isnull=True) | Q(email='')
basis = User.objects.exclude(NAMENSVERWEIS).exclude(username__startswith='geloescht_')
if '$1' == 'gruender':
    qs = basis.filter(groups__name='Gründer', is_active=True).filter(groups__name='Mitglied')
    qs = qs.exclude(ohne_mail)
elif '$1' == 'uebrige':
    qs = basis.filter(is_active=False).exclude(groups__name='Mitglied').exclude(ohne_mail)
else:
    qs = basis.filter(is_active=False).exclude(groups__name='Mitglied').filter(ohne_mail)
for name in qs.distinct().order_by('username').values_list('username', flat=True):
    print('USER\t' + name)
" 2>/dev/null | sed -n 's/^USER\t//p'
}

mapfile -t GRUENDER < <(liste gruender)
mapfile -t UEBRIGE < <(liste uebrige)
mapfile -t OHNE_MAIL < <(liste ohne_mail)

echo "Gruendungsmitglieder -> Datenbestaetigung (${#GRUENDER[@]}):"
printf '    %s\n' "${GRUENDER[@]}"
echo
echo "Uebrige Altkonten -> Antragslink (${#UEBRIGE[@]}):"
printf '    %s\n' "${UEBRIGE[@]}"
if [ "${#OHNE_MAIL[@]}" -gt 0 ]; then
    echo
    echo "Ohne E-Mail-Adresse, bekommen nichts (${#OHNE_MAIL[@]}) — Link ggf. per"
    echo "'send_antragslink --user NAME --print-url' holen:"
    printf '    %s\n' "${OHNE_MAIL[@]}"
fi
echo

if [ "${#GRUENDER[@]}" -ne 24 ]; then
    echo "ACHTUNG: erwartet waren 24 Gruendungsmitglieder, gefunden ${#GRUENDER[@]}." >&2
fi

if [ "${SENDEN}" -eq 0 ]; then
    echo "Probelauf — nichts verschickt. Senden mit: $0 --senden"
    exit 0
fi

read -r -p "Jetzt ${#GRUENDER[@]} Bestaetigungs- und ${#UEBRIGE[@]} Antragsmails senden? Tippe 'ja': " ANTWORT
if [ "${ANTWORT}" != "ja" ]; then
    echo "Abgebrochen, nichts verschickt."
    exit 1
fi

FEHLER=0
for name in "${GRUENDER[@]}"; do
    manage send_reconfirmation --user "${name}" || FEHLER=$((FEHLER + 1))
done
for name in "${UEBRIGE[@]}"; do
    manage send_antragslink --user "${name}" || FEHLER=$((FEHLER + 1))
done

echo
if [ "${FEHLER}" -gt 0 ]; then
    echo "Fertig, ${FEHLER} Aufruf(e) mit Fehler — Ausgabe oben pruefen." >&2
    exit 1
fi
echo "Fertig. Zeilen mit ERR oben pruefen; die Kommandos melden Versandfehler dort."
