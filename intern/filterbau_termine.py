"""Das Feld-Register der Terminliste.

Dieselbe Mechanik wie auf dem Repertoire (``filterbau.py``). Eine Eigenheit:

- **``past`` steht nicht hier.** Der Umschalter in der Titelleiste waehlt zwischen
  kommenden und vergangenen Terminen; er bleibt ein fester Parameter neben der Kette,
  den das Formular als verstecktes Feld weitertraegt (``traeger``). Die Chip-Adressen
  behalten ihn von selbst, sie kopieren die Query.
"""

from django.db.models import Q

from .filterbau import (
    Baukasten,
    Feld,
    bool_q,
    datum_feld,
    mehrfach_texte,
    namens_wert,
    paar,
    schalter_feld,
    text_feld,
    wahl_q,
)
from .models import OHNE_ANKUENDIGUNG

_ORT = (
    ("in", "ist in", False, "findet statt in {w}"),
    ("nicht-in", "ist nicht in", True, "findet nicht statt in {w}"),
)


def _angekuendigt_q(operator, werte):
    # Dieselbe Menge wie die Startseite (``home()``) -- siehe OHNE_ANKUENDIGUNG.
    return OHNE_ANKUENDIGUNG if operator == "nein" else ~OHNE_ANKUENDIGUNG


def _ablauf_q(operator, werte):
    # ``lieder_anzahl`` annotiert termin_list fuer die Markerspalte.
    treffer = Q(lieder_anzahl__gt=0)
    return ~treffer if operator == "nein" else treffer


FELDER = {
    "suche": text_feld("suche", "Suche", "kurz", "lang"),
    "datum": datum_feld("datum", "Datum", mit_uhrzeit=True),
    "ort": Feld(
        key="ort", label="Ort", art="mehrfach", operatoren=_ORT,
        q=wahl_q("ort"), werte_text=namens_wert,
        texte=mehrfach_texte("Ort", "Orte"),
    ),
    "angekuendigt": schalter_feld(
        "angekuendigt", "Auftritt",
        paar("öffentlich angekündigt", "nicht angekündigt",
             "ist öffentlich angekündigt", "ist nicht öffentlich angekündigt"),
        _angekuendigt_q,
    ),
    "repertoire": schalter_feld(
        "repertoire", "Konzert",
        paar("Konzert", "kein Konzert", "ist ein Konzert", "ist kein Konzert"),
        bool_q("repertoire"),
    ),
    "ablauf": schalter_feld(
        "ablauf", "Ablauf",
        paar("mit Ablauf", "ohne Ablauf", "hat einen Ablauf", "hat keinen Ablauf"),
        _ablauf_q,
    ),
    "anwesenheit": schalter_feld(
        "anwesenheit", "Anwesenheit",
        paar("mit Abfrage", "ohne Abfrage",
             "fragt die Anwesenheit ab", "fragt die Anwesenheit nicht ab"),
        bool_q("anwesenheit"),
    ),
}

FELD_REIHENFOLGE = (
    "suche", "datum", "ort", "angekuendigt", "repertoire", "ablauf", "anwesenheit",
)


def _eintraege(feld_key):
    if feld_key == "ort":
        from .models import Ort

        return [{"wert": str(o.pk), "label": o.name} for o in Ort.objects.order_by("name")]
    return []


def _traeger(daten):
    """Vergangene Termine bleiben vergangene, wenn das Filterformular abschickt."""
    return [("past", "1")] if daten.get("past") == "1" else []


TERMINE = Baukasten(
    felder=FELDER,
    reihenfolge=FELD_REIHENFOLGE,
    eintraege=_eintraege,
    traeger=_traeger,
)
