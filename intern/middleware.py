"""Sitzungspflege: die Ablauffrist gedrosselt verlängern.

``SESSION_SAVE_EVERY_REQUEST`` verlängerte die Frist bei *jeder* Anfrage — und
schrieb dafür jedes Mal die Sitzungszeile zurück, samt Transaktion und fsync.
Das traf nicht nur Seitenaufrufe: nginx prüft jede Datei unter ``/media/`` per
``auth_request`` gegen Django (siehe ``views/media.py``), und dazu kommen die
Polls von Forum und Benachrichtigungen. Eine Galerie mit 48 Vorschaubildern
löste so 48 schreibende Anfragen aus, die sich bei drei Arbeitsprozessen
gegenseitig ausbremsten. Gemessen: ``media-auth`` 22,5 ms mit, 1,5 ms ohne
diesen Rückschreibvorgang.

Stattdessen merkt sich die Sitzung den Zeitpunkt ihrer letzten Auffrischung und
wird nur noch alle ``AUFFRISCH_INTERVALL`` Sekunden geschrieben. Die Frist aus
``SESSION_COOKIE_AGE`` bleibt gleitend, ihr Startpunkt ist nur noch auf dieses
Intervall genau: Wer untätig ist, wird bis zu ``AUFFRISCH_INTERVALL`` früher
abgemeldet als vorher — bei vier Stunden Frist und fünf Minuten Intervall ein
Unterschied von zwei Prozent.

Nicht betroffen ist alles, was die Sitzung ohnehin verändert (Login, das
weggeklickte Termin-Banner): Django schreibt sie dann wie bisher sofort.
"""

import time

AUFFRISCH_INTERVALL = 300  # Sekunden

# Schlüssel in der Sitzung. Der Unterstrich hält ihn von fachlichen Werten
# getrennt, wie bei Djangos eigenen ``_auth_user_*``.
STAND_SCHLUESSEL = "_aufgefrischt"


def muss_auffrischen(stand, jetzt, intervall=AUFFRISCH_INTERVALL):
    """Ist die Sitzungsfrist fällig? ``stand``/``jetzt`` sind Sekunden seit Epoche.

    Ohne bisherigen Stand (``None`` — Sitzung aus der Zeit vor dieser Drosselung,
    oder gerade erst angelegt) ist sie fällig. Ein Stand aus der Zukunft — die
    Systemuhr wurde zurückgestellt — gilt ebenfalls als fällig, sonst bliebe die
    Sitzung bis zum Erreichen dieses Zeitpunkts ungeschrieben.
    """
    if stand is None:
        return True
    try:
        stand = int(stand)
    except (TypeError, ValueError):
        return True
    return not (0 <= jetzt - stand < intervall)


class SitzungAuffrischen:
    """Verlängert die Sitzungsfrist höchstens alle ``AUFFRISCH_INTERVALL`` Sekunden.

    Gehört hinter ``AuthenticationMiddleware``: Anonyme Anfragen haben keine
    Sitzung, die es zu halten lohnte — für sie würde das Schreiben erst eine
    anlegen.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        sitzung = getattr(request, "session", None)
        nutzer = getattr(request, "user", None)
        if sitzung is not None and nutzer is not None and nutzer.is_authenticated:
            jetzt = int(time.time())
            # Intervall ausdrücklich übergeben, nicht über den Vorgabewert: so
            # wirkt ein geändertes AUFFRISCH_INTERVALL auch nachträglich.
            if muss_auffrischen(sitzung.get(STAND_SCHLUESSEL), jetzt, AUFFRISCH_INTERVALL):
                # Das Setzen markiert die Sitzung als geändert; Django schreibt
                # sie am Ende der Anfrage und schiebt dabei ``expire_date`` vor.
                sitzung[STAND_SCHLUESSEL] = jetzt
        return self.get_response(request)
