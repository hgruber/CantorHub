"""Das Feld-Register der Orte.

Dieselbe Mechanik wie auf Mitgliederliste und Repertoire (``filterbau.py``). Die
Orte haben keine Schranke und keine Mehrfachrelation: lauter Textfelder plus ein
fester Schalter, ob der Ort auf der Karte liegt.
"""

from django.db.models import Q

from .filterbau import Baukasten, paar, schalter_feld, text_feld


def _koordinaten_q(operator, werte):
    treffer = Q(breite__isnull=False, laenge__isnull=False)
    return ~treffer if operator == "nein" else treffer


FELDER = {
    "suche": text_feld("suche", "Suche", "name", "strasse", "ort", "beschreibung"),
    "name": text_feld("name", "Name"),
    "strasse": text_feld("strasse", "Straße"),
    "plz": text_feld("plz", "PLZ"),
    "ort": text_feld("ort", "Ort"),
    "beschreibung": text_feld("beschreibung", "Beschreibung"),
    "karte": schalter_feld(
        "karte", "Karte",
        paar("auf der Karte", "nicht auf der Karte", "liegt auf der Karte", "hat keine Koordinaten"),
        _koordinaten_q,
    ),
}

# Reihenfolge im Feld-Dropdown -- die Reihenfolge der Tabellenspalten.
FELD_REIHENFOLGE = ("suche", "name", "strasse", "plz", "ort", "beschreibung", "karte")


ORTE = Baukasten(felder=FELDER, reihenfolge=FELD_REIHENFOLGE)
