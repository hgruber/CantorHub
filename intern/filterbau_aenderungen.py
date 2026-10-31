"""Das Feld-Register des Änderungsprotokolls.

Es loest das letzte ``FilterSet`` ab (``ChangeLogFilter``). Zwei Eigenheiten:

- **Zwei Sonderwerte.** „System" (``__system__``) sind Eintraege ohne Benutzer,
  „Gruppenzuordnung" (``__gruppe__``) sind Mitglieds-Aenderungen an den Gruppen --
  beide Werte stehen neben den echten in derselben Auswahl, wie frueher.
- **Die alten Parameter** (``model_name``, ``action``, ``user``, ``gruppe``,
  ``datum_von``, ``datum_bis``) uebersetzt ``alt_parameter``, damit ein gemerkter
  Filter im Cookie gueltig bleibt. ``datum_von``/``datum_bis`` schlossen den Tag ein,
  „nach"/„vor" schliessen ihn aus -- die Uebersetzung rueckt deshalb einen Tag weiter.

Die Beschriftungen kommen aus ``views/aenderungen.py`` (``MODEL_LABELS``), dem einen
Ort, an dem das Protokoll seine Bereiche benennt; der Import liegt in den Funktionen,
weil ``intern.views`` beim Laden dieses Modul nachzieht.
"""

from datetime import date, timedelta

from django.db.models import Exists, OuterRef, Q

from .filterbau import (
    AUSWAHL,
    Baukasten,
    Bedingung,
    Feld,
    auswahl_feld,
    datum_feld,
    mehrfach_texte,
    namens_wert,
)
from .models import ChangeLog, User

SYSTEM = "__system__"
GRUPPENZUORDNUNG = "__gruppe__"

_BENUTZER = (
    ("in", "ist", False, "von {w}"),
    ("nicht-in", "ist nicht", True, "nicht von {w}"),
)
_GRUPPE = (
    ("in", "ist in", False, "von Mitgliedern der Gruppe {w}"),
    ("nicht-in", "ist nicht in", True, "nicht von Mitgliedern der Gruppe {w}"),
)


def _bereich_q(operator, werte):
    wert = werte[0]
    if wert == GRUPPENZUORDNUNG:
        treffer = Q(model_name="User", changes__has_key="gruppe")
    else:
        treffer = Q(model_name=wert)
    return treffer if operator == "ist" else ~treffer


def _benutzer_q(operator, werte):
    ids = [int(w) for w in werte if w.isdigit()]
    treffer = Q(user_id__in=ids)
    if SYSTEM in werte:
        treffer |= Q(user__isnull=True)
    return treffer if operator == "in" else ~treffer


def _gruppe_q(operator, werte):
    # EXISTS statt Join -- siehe ``Feld``: die Verneinung soll den Eintrag pruefen.
    treffer = Exists(User.objects.filter(pk=OuterRef("user_id"), groups__pk__in=werte))
    return treffer if operator == "in" else ~treffer


FELDER = {
    "bereich": Feld(
        key="bereich", label="Bereich", art="auswahl",
        operatoren=AUSWAHL,
        q=_bereich_q, werte_text=namens_wert,
    ),
    "aktion": auswahl_feld("aktion", "Aktion", "action"),
    "benutzer": Feld(
        key="benutzer", label="Benutzer", art="mehrfach", operatoren=_BENUTZER,
        q=_benutzer_q, werte_text=namens_wert,
        texte=mehrfach_texte("Benutzer", "Benutzer"),
    ),
    "gruppe": Feld(
        key="gruppe", label="Gruppe", art="mehrfach", operatoren=_GRUPPE,
        q=_gruppe_q, werte_text=namens_wert,
        texte=mehrfach_texte("Gruppe", "Gruppen"),
    ),
    "datum": datum_feld("datum", "Datum", "timestamp", mit_uhrzeit=True),
}

FELD_REIHENFOLGE = ("datum", "benutzer", "gruppe", "bereich", "aktion")


# ------------------------------------------------------- Eigenheiten der Seite


def bereiche():
    from .views.aenderungen import MODEL_LABELS

    return {GRUPPENZUORDNUNG: "Gruppenzuordnung", **MODEL_LABELS}


def aktionen():
    return dict(ChangeLog.ACTION_CHOICES)


def benutzer():
    """„System" und die aktiven Konten, nach Stimme und Name wie frueher."""
    konten = (
        User.objects.filter(is_active=True)
        .annotate(_stimme_pos=User.stimme_order_case())
        .order_by("_stimme_pos", "last_name", "first_name")
    )
    namen = {SYSTEM: "System"}
    for u in konten:
        namen[str(u.pk)] = f"{u.last_name}, {u.first_name}".strip(", ") or u.username
    return namen


def gruppen():
    from django.contrib.auth.models import Group

    return {str(g.pk): g.name for g in Group.objects.order_by("name")}


_QUELLEN = {"bereich": bereiche, "aktion": aktionen, "benutzer": benutzer, "gruppe": gruppen}


def _eintraege(feld_key):
    quelle = _QUELLEN.get(feld_key)
    if not quelle:
        return []
    return [{"wert": wert, "label": label} for wert, label in quelle().items()]


def chip_namen(bedingungen):
    """Kennung -> Name fuer die Chips -- nur fuer die Felder, die die Kette nennt."""
    return {b.feld: _QUELLEN[b.feld]() for b in bedingungen if b.feld in _QUELLEN}


def _tag(wert, verschiebung):
    try:
        return (date.fromisoformat(wert) + timedelta(days=verschiebung)).isoformat()
    except ValueError:
        return None


def _alt_parameter(daten):
    """Die Felder des alten ``ChangeLogFilter``."""
    bedingungen = []

    def wert(name):
        return (daten.get(name) or "").strip()

    if wert("model_name"):
        bedingungen.append(Bedingung("und", "bereich", "ist", (wert("model_name"),)))
    if wert("action"):
        bedingungen.append(Bedingung("und", "aktion", "ist", (wert("action"),)))
    if wert("user"):
        bedingungen.append(Bedingung("und", "benutzer", "in", (wert("user"),)))
    if wert("gruppe"):
        bedingungen.append(Bedingung("und", "gruppe", "in", (wert("gruppe"),)))
    # „von" und „bis" schlossen den Tag ein.
    for name, operator, verschiebung in (("datum_von", "nach", -1), ("datum_bis", "vor", 1)):
        tag = _tag(wert(name), verschiebung) if wert(name) else None
        if tag:
            bedingungen.append(Bedingung("und", "datum", operator, (tag,)))
    return bedingungen


AENDERUNGEN = Baukasten(
    felder=FELDER,
    reihenfolge=FELD_REIHENFOLGE,
    eintraege=_eintraege,
    alt_parameter=_alt_parameter,
)
