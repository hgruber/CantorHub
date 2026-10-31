"""Das Feld-Register der Orte.

Dieselbe Mechanik wie auf Mitgliederliste und Repertoire (``filterbau.py``). Die
Orte haben keine Schranke und keine Mehrfachrelation: lauter Textfelder plus ein
fester Schalter, ob der Ort auf der Karte liegt.
"""

from django.db.models import Q

from .filterbau import Baukasten, Feld, text_q, text_wert

_TEXT = (
    ("enthaelt", "enthält", False, "{feld} enthält {w}"),
    ("enthaelt-nicht", "enthält nicht", True, "{feld} enthält nicht {w}"),
    ("beginnt", "beginnt mit", False, "{feld} beginnt mit {w}"),
    ("endet", "endet mit", False, "{feld} endet mit {w}"),
    ("ist", "ist", False, "{feld} ist {w}"),
)


def _text_feld(key, label, *feldnamen):
    return Feld(
        key=key, label=label, art="text", operatoren=_TEXT,
        q=text_q(*(feldnamen or (key,))), werte_text=text_wert,
    )


def _koordinaten_q(operator, werte):
    treffer = Q(breite__isnull=False, laenge__isnull=False)
    return ~treffer if operator == "nein" else treffer


FELDER = {
    "suche": _text_feld("suche", "Suche", "name", "strasse", "ort", "beschreibung"),
    "name": _text_feld("name", "Name"),
    "strasse": _text_feld("strasse", "Straße"),
    "plz": _text_feld("plz", "PLZ"),
    "ort": _text_feld("ort", "Ort"),
    "beschreibung": _text_feld("beschreibung", "Beschreibung"),
    "karte": Feld(
        key="karte", label="Karte", art="ohne",
        operatoren=(
            ("ja", "auf der Karte", False, "liegt auf der Karte"),
            ("nein", "nicht auf der Karte", True, "hat keine Koordinaten"),
        ),
        q=_koordinaten_q, werte_text=lambda werte, namen: "", ohne_wert=True,
    ),
}

# Reihenfolge im Feld-Dropdown -- die Reihenfolge der Tabellenspalten.
FELD_REIHENFOLGE = ("suche", "name", "strasse", "plz", "ort", "beschreibung", "karte")


ORTE = Baukasten(felder=FELDER, reihenfolge=FELD_REIHENFOLGE)
