"""Das Feld-Register des Repertoires.

Dasselbe Konzept wie auf der Mitgliederliste (Mechanik in ``filterbau.py``), nur mit
Liedern statt Personen. Zwei Eigenheiten dieser Seite:

- **Kein Recht am Feld.** Das Repertoire hat keine Schranke; wer angemeldet ist,
  sieht und filtert alles.
- **``konzert`` steht nicht hier.** Derselbe Parameter steuert auch den Ablauf-Modus
  und die Warteschlangen des Abspielers -- er bleibt ein festes Feld neben der Kette
  (siehe ``views/titel.py``).
"""

from django.db.models import Exists, OuterRef, Q

from .filterbau import (
    Baukasten,
    Bedingung,
    Feld,
    auswahl_feld,
    bool_q,
    mehrfach_texte,
    namens_wert,
    paar,
    schalter_feld,
    text_feld,
)
from .models import Lied, LiedDatei, User

_SOLIST = (
    ("in", "ist Solist", False, "hat {w} als Solist"),
    ("nicht-in", "ist nicht Solist", True, "hat {w} nicht als Solist"),
)
_DIRIGENT = (
    ("in", "ist Dirigent", False, "hat {w} als Dirigent"),
    ("nicht-in", "ist nicht Dirigent", True, "hat {w} nicht als Dirigent"),
)


# ------------------------------------------------------------------ Q-Bauer


def _rolle_q(rolle):
    """Hat das Lied eine Datei dieser Rolle? EXISTS auf die Rollenzeile.

    Ohne Join, damit die Verneinung das Lied prueft und nicht eine einzelne
    Verknuepfungszeile."""
    def q(operator, werte):
        treffer = Q(Exists(LiedDatei.objects.filter(lied=OuterRef("pk"), rolle=rolle)))
        return ~treffer if operator == "nein" else treffer

    return q


def _personen_q(feldname):
    """Solist und Dirigent sind Mehrfachrelationen -- als EXISTS-Unterabfrage.

    Als Join mit Verneinung pruefte Django die einzelne Verknuepfungszeile statt des
    Lieds; ein Lied mit zwei Solisten rutschte durch den Ausschluss. Ohne Join gibt es
    auch keine doppelten Koepfe, also braucht es kein ``.distinct()``.
    """
    def q(operator, werte):
        treffer = Exists(
            Lied.objects.filter(
                pk=OuterRef("pk"), **{feldname + "__pk__in": werte}
            )
        )
        return treffer if operator == "in" else ~treffer

    return q


def _flag(key, label, *saetze):
    return schalter_feld(key, label, paar(*saetze), bool_q(key))


def _rolle(key, label, rolle, *saetze):
    return schalter_feld(key, label, paar(*saetze), _rolle_q(rolle))


# --------------------------------------------------------------- Die Felder


FELDER = {
    "suche": text_feld("suche", "Suche", "titel", "komponist", "bearbeiter"),
    "tempo": auswahl_feld("tempo", "Tempo"),
    "tonart": auswahl_feld("tonart", "Tonart"),
    "aktiv": _flag("aktiv", "Repertoire", "aktiv", "archiviert", "ist aktiv", "ist archiviert"),
    "hymne": _flag("hymne", "Hymne", "Hymne", "keine Hymne", "ist eine Hymne", "ist keine Hymne"),
    "acapella": _flag("acapella", "A cappella", "a cappella", "nicht a cappella", "ist a cappella", "ist nicht a cappella"),
    "weihnacht": _flag("weihnacht", "Weihnachten", "Weihnachtslied", "kein Weihnachtslied", "ist ein Weihnachtslied", "ist kein Weihnachtslied"),
    "original": _rolle("original", "Original", "original", "Original", "kein Original", "hat ein Original", "hat kein Original"),
    "aufnahme": _rolle("aufnahme", "Aufnahme", "aufnahme", "Aufnahme", "keine Aufnahme", "hat eine Aufnahme", "hat keine Aufnahme"),
    "pdf": _rolle("pdf", "Notenblatt", "notenblatt", "Notenblatt", "kein Notenblatt", "hat ein Notenblatt", "hat kein Notenblatt"),
    "noten": _rolle("noten", "Notensatz", "notensatz", "Notensatz", "kein Notensatz", "hat einen Notensatz", "hat keinen Notensatz"),
    "text": _rolle("text", "Liedtext", "text", "Liedtext", "kein Liedtext", "hat einen Liedtext", "hat keinen Liedtext"),
    "solist": Feld(
        key="solist", label="Solist", art="mehrfach", operatoren=_SOLIST,
        q=_personen_q("solist"), werte_text=namens_wert,
        texte=mehrfach_texte("Solist", "Solisten"),
    ),
    "dirigent": Feld(
        key="dirigent", label="Dirigent", art="mehrfach", operatoren=_DIRIGENT,
        q=_personen_q("dirigent"), werte_text=namens_wert,
        texte=mehrfach_texte("Dirigent", "Dirigenten"),
    ),
}

# Reihenfolge im Feld-Dropdown -- die Reihenfolge der Tabellenspalten.
FELD_REIHENFOLGE = (
    "suche", "tempo", "tonart", "aktiv", "hymne", "acapella", "weihnacht",
    "original", "aufnahme", "pdf", "noten", "text", "solist", "dirigent",
)


# ------------------------------------------------------- Eigenheiten der Seite


def _personen_qs(feldname):
    return (
        User.objects.filter(**{feldname + "__isnull": False}, is_active=True)
        .distinct()
        .order_by("last_name", "first_name")
    )


def _eintraege(feld_key):
    if feld_key == "tempo":
        # Die Tabelle schreibt Tempo aus („Schnell"), Lied.CHOICES nur „s".
        from .tables import _TEMPO_LABELS

        return [{"wert": w, "label": _TEMPO_LABELS.get(w, l)} for w, l in Lied.CHOICES]
    if feld_key == "tonart":
        return [{"wert": w, "label": l} for w, l in Lied.TONART_CHOICES]
    if feld_key in ("solist", "dirigent"):
        return [
            {"wert": str(u.pk), "label": f"{u.last_name}, {u.first_name}".strip(", ")}
            for u in _personen_qs(feld_key)
        ]
    return []


# Die festen Filterfelder von vor dem Baukasten -- ein gemerkter Filter im Cookie
# traegt sie noch. Uebersetzt werden die **Parameternamen des alten FilterSet**,
# nicht die Modellfelder: „sheet" gehoert zu `pdf`, „notensatz" zu `noten`.
def _alt_parameter(daten):
    bedingungen = []

    def zahlen(name):
        return [w for w in daten.getlist(name) if w]

    suche = (daten.get("titel") or "").strip()
    if suche:
        bedingungen.append(Bedingung("und", "suche", "enthaelt", (suche,)))

    for name in ("tempo", "tonart"):
        wert = (daten.get(name) or "").strip()
        if wert:
            bedingungen.append(Bedingung("und", name, "ist", (wert,)))

    # Die acht Drei-Zustand-Schalter: true/false, "unknown" hiess „Egal".
    for name in ("aktiv", "hymne", "acapella", "weihnacht"):
        wert = (daten.get(name) or "").strip()
        if wert in ("true", "1"):
            bedingungen.append(Bedingung("und", name, "ja", ()))
        elif wert in ("false", "0"):
            bedingungen.append(Bedingung("und", name, "nein", ()))

    for alt, key in (("original", "original"), ("aufnahme", "aufnahme"),
                     ("sheet", "pdf"), ("notensatz", "noten")):
        wert = (daten.get(alt) or "").strip()
        if wert in ("true", "1"):
            bedingungen.append(Bedingung("und", key, "ja", ()))
        elif wert in ("false", "0"):
            bedingungen.append(Bedingung("und", key, "nein", ()))

    for name in ("solist", "dirigent"):
        werte = zahlen(name)
        if werte:
            bedingungen.append(Bedingung("und", name, "in", tuple(werte)))

    return bedingungen


TITEL = Baukasten(
    felder=FELDER,
    reihenfolge=FELD_REIHENFOLGE,
    eintraege=_eintraege,
    alt_parameter=_alt_parameter,
)
