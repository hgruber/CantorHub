"""Telefonnummern in einheitlicher internationaler Schreibweise.

Nur Regeln, keine Datenbank: die beiden Aufrufer sind ``TelefonNormalisierungMixin``
in ``forms.py`` und das Kommando ``telefonnummern_normalisieren``. Die Landesvorwahl
kommt als Argument herein (Konfigurationsschlüssel ``TELEFON_LANDESVORWAHL``), damit
das Modul ohne Django auskommt und ``SimpleTestCase`` es prüfen kann.

Die Gruppierung ist eine Lesehilfe: gesetzt werden ausschließlich Trenner, die Ziffern
bleiben unangetastet. Zwei Unschärfen sind bewusst in Kauf genommen:

* Die rund hundert fünfstelligen Ortsnetzkennzahlen (33xxx, 35xxx, 36xxx, 38xxx,
  39xxx) werden vierstellig getrennt — ``+49 3587 312345`` statt ``+49 35873 12345``.
* Eine Durchwahl verliert ihren Bindestrich: ``069 1234567-21`` wird
  ``+49 69 123456721``. Die Nummer bleibt vollständig und wählbar, nur die Lesart
  verschiebt sich.

Lesbar gruppiert wird nur, wofür ein Nummernplan hinterlegt ist — heute allein
``+49``. Jede andere Landesvorwahl wird kompakt gespeichert (``+41441234567``).
"""

import re

LANDESVORWAHL_STANDARD = "+49"

# Entspricht User.telefon.max_length (intern/models.py:85).
MAX_LAENGE = 32

# Die Felder, die eine Nummer halten — eine Quelle für Formular und Kommando.
FELDER = ("telefon", "telefon_mobil", "telefon_job", "telefon_job_mobil", "fax")

# Zeichen, die in einer getippten Nummer vorkommen dürfen. Alles andere — Buchstaben,
# Komma, Klartext wie „nur abends“ — heißt: das ist keine einzelne Nummer.
_ERLAUBTE_ZEICHEN = re.compile(r"^[0-9+\s().:/-]+$")

_LANDESVORWAHL = re.compile(r"^\+\d{1,3}$")

# Landesvorwahlen mit zwei Ziffern. In E.164 sind die Zonen 1 und 7 einstellig,
# diese hier zweistellig, alle übrigen dreistellig.
_ZWEISTELLIGE_LAENDER = frozenset({
    "20", "27",
    "30", "31", "32", "33", "34", "36", "39",
    "40", "41", "43", "44", "45", "46", "47", "48", "49",
    "51", "52", "53", "54", "55", "56", "57", "58",
    "60", "61", "62", "63", "64", "65", "66",
    "81", "82", "84", "86",
    "90", "91", "92", "93", "94", "95", "98",
})

# --- Deutscher Nummernplan -------------------------------------------------------
# Zweistellige Ortsnetzkennzahlen und die nationalen Teilnehmerrufnummern 032.
_DE_ZWEISTELLIG = frozenset({"30", "40", "69", "89", "32"})

# Mobilfunkblöcke mit vierstelliger Kennzahl; stehen vor den dreistelligen, weil
# „1573“ sonst als „157“ gelesen würde.
_DE_VIERSTELLIG = frozenset({"1570", "1573", "1575", "1577", "1578", "1579"})

_DE_DREISTELLIG = frozenset({
    # Mobilfunk
    "150", "151", "152", "155", "156", "157", "159",
    "160", "162", "163",
    "170", "171", "172", "173", "174", "175", "176", "177", "178", "179",
    # Dienste
    "137", "180", "700", "800", "900",
    # Ortsnetzkennzahlen, die nicht auf 1 enden und daher nicht unter die Regel
    # in _de_vorwahllaenge fallen
    "201", "202", "203", "208", "209", "212", "214", "228", "234",
    "335", "340", "345", "355", "365", "375", "385", "395",
})

# Vergessene Verkehrsausscheidungsziffer: „170 1234567“ statt „0170 1234567“ ist der
# häufigste Tippfehler und eindeutig, weil diese Bereiche keine Ortsnetze sind.
_DE_OHNE_NULL = ("15", "16", "17")


def _de_vorwahllaenge(national):
    """Länge der Ortsnetzkennzahl — nur zum Setzen der Trenner.

    Die deutschen Ortsnetzkennzahlen sind präfixfrei: zu einer gültigen dreistelligen
    ``ab1`` kann es keine vierstellige ``ab1c`` geben, und die vierstelligen (6151,
    2161, 5121, 7121 …) tragen an dritter Stelle nie eine 1. Darum genügt die Regel
    unten samt der Ausnahmeliste, statt achtzig Vorwahlen aufzuzählen.
    """
    if national[:2] in _DE_ZWEISTELLIG:
        return 2
    if national[:4] in _DE_VIERSTELLIG:
        return 4
    if national[:3] in _DE_DREISTELLIG:
        return 3
    if national[2] == "1":
        return 3            # 211, 221, 611, 711, 911 …
    return 4


# Landesvorwahl -> Funktion, die die Länge der Ortsnetzkennzahl liefert. Fehlt der
# Eintrag, wird nicht gruppiert.
_NUMMERNPLAN = {"+49": _de_vorwahllaenge}


def _laendervorwahl_laenge(ziffern):
    if ziffern[0] in "17":
        return 1
    if ziffern[:2] in _ZWEISTELLIGE_LAENDER:
        return 2
    return 3


def normalisiere(roh, landesvorwahl=LANDESVORWAHL_STANDARD):
    """Die Nummer in internationaler Schreibweise, sonst ``None``.

    ``""`` für eine leere Eingabe, ``None`` wenn sich keine Nummer erkennen lässt —
    wie ``syncthing.geraete_id()`` und ohne Ausnahme, damit die Aufrufer keinen
    ``try``-Block brauchen.
    """
    text = (roh or "").strip()
    if not text:
        return ""
    # „+49 (0)170 …“ ist verbreitet; dort gehört die Null nicht hin.
    text = text.replace("(0)", "")
    if not _ERLAUBTE_ZEICHEN.match(text):
        return None
    if "+" in text[1:]:
        return None
    if not _LANDESVORWAHL.match(landesvorwahl or ""):
        landesvorwahl = LANDESVORWAHL_STANDARD

    ziffern = re.sub(r"\D", "", text)
    if not ziffern:
        return None
    eigenes_land = landesvorwahl.lstrip("+")

    if text.startswith("+"):
        pass
    elif ziffern.startswith("00"):
        ziffern = ziffern[2:]
    elif ziffern.startswith("0"):
        ziffern = eigenes_land + ziffern[1:]
    elif landesvorwahl in _NUMMERNPLAN and (
        ziffern[:2] in _DE_OHNE_NULL or ziffern[:3] in _DE_DREISTELLIG
    ):
        ziffern = eigenes_land + ziffern
    else:
        # Eine Ortsnetznummer ohne Vorwahl lässt sich nicht international schreiben,
        # und eine Vorwahl zu erfinden wäre falsch.
        return None

    if ziffern.startswith("0"):
        return None                     # keine Landesvorwahl beginnt mit einer Null
    if not 7 <= len(ziffern) <= 15:      # E.164
        return None

    vorwahl = ziffern[:_laendervorwahl_laenge(ziffern)]
    national = ziffern[len(vorwahl):]
    laenge = _NUMMERNPLAN.get("+" + vorwahl)
    if laenge is None or not national:
        ergebnis = f"+{ziffern}"
    else:
        trenn = min(laenge(national), len(national) - 1)
        ergebnis = f"+{vorwahl} {national[:trenn]} {national[trenn:]}"

    # Länger als MAX_LAENGE kann das nicht werden (ein Plus, 15 Ziffern, zwei Trenner
    # sind 18 Zeichen); die Schranke steht, weil models.py:85 sie setzt.
    return ergebnis if len(ergebnis) <= MAX_LAENGE else None
