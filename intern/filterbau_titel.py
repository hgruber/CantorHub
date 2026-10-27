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
    namens_wert,
    text_q,
    text_wert,
    wahl_q,
)
from .models import Lied, LiedDatei, User

def _paar(kurz_ja, kurz_nein, satz_ja, satz_nein):
    """Ein Ja/Nein-Paar: je Stellung eine kurze Beschriftung (die zugleich der
    Tooltip des Drei-Zustand-Schalters ist) und der Satz des Chips. Beide sind
    noetig, weil „hat ein Original" und „kein Original" sich nicht aus einer
    gemeinsamen Vorlage ergeben."""
    return (
        ("ja", kurz_ja, False, satz_ja),
        ("nein", kurz_nein, True, satz_nein),
    )


_AUSWAHL = (
    ("ist", "ist", False, "{feld} ist {w}"),
    ("ist-nicht", "ist nicht", True, "{feld} ist nicht {w}"),
)
_SOLIST = (
    ("in", "ist Solist", False, "hat {w} als Solist"),
    ("nicht-in", "ist nicht Solist", True, "hat {w} nicht als Solist"),
)
_DIRIGENT = (
    ("in", "ist Dirigent", False, "hat {w} als Dirigent"),
    ("nicht-in", "ist nicht Dirigent", True, "hat {w} nicht als Dirigent"),
)
_TEXT = (
    ("enthaelt", "enthält", False, "{feld} enthält {w}"),
    ("enthaelt-nicht", "enthält nicht", True, "{feld} enthält nicht {w}"),
    ("beginnt", "beginnt mit", False, "{feld} beginnt mit {w}"),
    ("endet", "endet mit", False, "{feld} endet mit {w}"),
    ("ist", "ist", False, "{feld} ist {w}"),
)


# ------------------------------------------------------------------ Q-Bauer


def _bool_q(feldname):
    def q(operator, werte):
        return Q(**{feldname: operator == "ja"})

    return q


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


def _wahl_feld(key, label, ausdruck):
    """Ein Feld auf einer gewoehnlichen Spalte: erlaubte Werte, mit ODER verknuepft."""
    return Feld(
        key=key, label=label, art="auswahl", operatoren=_AUSWAHL,
        q=wahl_q(ausdruck, "ist", "ist-nicht"), werte_text=wahl_wert,
    )


def wahl_wert(werte, namen):
    return ", ".join((namen or {}).get(w, w) for w in werte)


# --------------------------------------------------------------- Die Felder


FELDER = {
    "suche": Feld(
        key="suche", label="Suche", art="text", operatoren=_TEXT,
        q=text_q("titel", "komponist", "bearbeiter"), werte_text=text_wert,
    ),
    "tempo": _wahl_feld("tempo", "Tempo", "tempo"),
    "tonart": _wahl_feld("tonart", "Tonart", "tonart"),
    "aktiv": Feld(
        key="aktiv", label="Repertoire", art="ohne", operatoren=_paar("aktiv", "archiviert", "ist aktiv", "ist archiviert"),
        q=_bool_q("aktiv"), werte_text=lambda werte, namen: "", ohne_wert=True,
    ),
    "hymne": Feld(
        key="hymne", label="Hymne", art="ohne", operatoren=_paar("Hymne", "keine Hymne", "ist eine Hymne", "ist keine Hymne"),
        q=_bool_q("hymne"), werte_text=lambda werte, namen: "", ohne_wert=True,
    ),
    "acapella": Feld(
        key="acapella", label="A cappella", art="ohne", operatoren=_paar("a cappella", "nicht a cappella", "ist a cappella", "ist nicht a cappella"),
        q=_bool_q("acapella"), werte_text=lambda werte, namen: "", ohne_wert=True,
    ),
    "weihnacht": Feld(
        key="weihnacht", label="Weihnachten", art="ohne", operatoren=_paar("Weihnachtslied", "kein Weihnachtslied", "ist ein Weihnachtslied", "ist kein Weihnachtslied"),
        q=_bool_q("weihnacht"), werte_text=lambda werte, namen: "", ohne_wert=True,
    ),
    "original": Feld(
        key="original", label="Original", art="ohne",
        operatoren=_paar("Original", "kein Original", "hat ein Original", "hat kein Original"),
        q=_rolle_q("original"), werte_text=lambda werte, namen: "", ohne_wert=True,
    ),
    "aufnahme": Feld(
        key="aufnahme", label="Aufnahme", art="ohne",
        operatoren=_paar("Aufnahme", "keine Aufnahme", "hat eine Aufnahme", "hat keine Aufnahme"),
        q=_rolle_q("aufnahme"), werte_text=lambda werte, namen: "", ohne_wert=True,
    ),
    "pdf": Feld(
        key="pdf", label="Notenblatt", art="ohne",
        operatoren=_paar("Notenblatt", "kein Notenblatt", "hat ein Notenblatt", "hat kein Notenblatt"),
        q=_rolle_q("notenblatt"), werte_text=lambda werte, namen: "", ohne_wert=True,
    ),
    "noten": Feld(
        key="noten", label="Notensatz", art="ohne",
        operatoren=_paar("Notensatz", "kein Notensatz", "hat einen Notensatz", "hat keinen Notensatz"),
        q=_rolle_q("notensatz"), werte_text=lambda werte, namen: "", ohne_wert=True,
    ),
    "text": Feld(
        key="text", label="Liedtext", art="ohne",
        operatoren=_paar("Liedtext", "kein Liedtext", "hat einen Liedtext", "hat keinen Liedtext"),
        q=_rolle_q("text"), werte_text=lambda werte, namen: "", ohne_wert=True,
    ),
    "solist": Feld(
        key="solist", label="Solist", art="mehrfach", operatoren=_SOLIST,
        q=_personen_q("solist"), werte_text=namens_wert,
        texte={"auswahl_label": "Gewählte Solisten", "vorrat_label": "Verfügbare Solisten",
               "such_platzhalter": "Solist suchen …", "leer_text": "Alle Solisten"},
    ),
    "dirigent": Feld(
        key="dirigent", label="Dirigent", art="mehrfach", operatoren=_DIRIGENT,
        q=_personen_q("dirigent"), werte_text=namens_wert,
        texte={"auswahl_label": "Gewählte Dirigenten", "vorrat_label": "Verfügbare Dirigenten",
               "such_platzhalter": "Dirigent suchen …", "leer_text": "Alle Dirigenten"},
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
