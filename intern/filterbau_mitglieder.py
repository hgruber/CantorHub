"""Das Feld-Register der Mitgliederliste.

Die Felder, die Q-Bauer, die es nur hier gibt, und die drei Eigenheiten dieser Seite:
die Zugangs-Vorgabe der Verwalter, die Uebersetzung der alten Filterparameter und der
``zugang=egal``-Marker an den Chips. Die Mechanik steht in ``filterbau.py``.

**Das Recht am Feld ist hier zu Hause.** Der Filter laeuft VOR der Schwaerzung in
``MitgliederTabelle``; ein Kriterium auf einem verborgenen Feld verriete dessen Wert
ueber die Treffermenge. Kontaktangaben, die ein Mitglied verbergen kann
(``mitglied_felder.PRIVACY_FIELDS``), und der Zugangsschalter bekommen deshalb
``RECHT_VERWALTER``.
"""

from django.contrib.auth.models import Group
from django.db.models import Exists, OuterRef, Q

from .filterbau import (
    RECHT_VERWALTER,
    Baukasten,
    Bedingung,
    Feld,
    datum_q,
    datum_wert,
    namens_wert,
    text_q,
    text_wert,
    wahl_q,
)
from .models import User, Zusage

# Der Marker, mit dem ein Verwalter die Zugangs-Vorgabe abwaehlt: ``?zugang=egal``.
# Ohne ihn haengt der Baukasten „Zugang: hat" von selbst an, damit die Liste wie
# bisher nur Konten mit Portalzugang zeigt.
ZUGANG_EGAL = "egal"


# ------------------------------------------------------------- Operatorensaetze
#
# Jeder Operator traegt seinen Satzbaustein fertig ausformuliert -- mit „nicht", wo
# es hingehoert, und ohne, wo nicht. Ein angehaengtes „nicht" vor dem ganzen Satz
# ergaebe „nicht hat keinen Zugang".

_GRUPPEN = (
    ("in", "ist in", False, "ist in Gruppe {w}"),
    ("nicht-in", "ist nicht in", True, "ist nicht in Gruppe {w}"),
)
_STIMME = (
    ("in", "ist in", False, "ist {w}"),
    ("nicht-in", "ist nicht in", True, "ist nicht {w}"),
)
_TEXT = (
    ("enthaelt", "enthält", False, "{feld} enthält {w}"),
    ("enthaelt-nicht", "enthält nicht", True, "{feld} enthält nicht {w}"),
    ("beginnt", "beginnt mit", False, "{feld} beginnt mit {w}"),
    ("endet", "endet mit", False, "{feld} endet mit {w}"),
    ("ist", "ist", False, "{feld} ist {w}"),
)
_HAT = (
    ("hat", "hat", False, "{w}"),
    ("hat-nicht", "hat nicht", True, "nicht {w}"),
)
_ZUGANG = (
    ("hat", "hat Zugang", False, "hat Zugang"),
    ("hat-nicht", "hat keinen Zugang", True, "hat keinen Zugang"),
)
_DATUM = (
    ("vor", "vor", False, "{feld} vor dem {w}"),
    ("nach", "nach", False, "{feld} nach dem {w}"),
    ("ist", "am", False, "{feld} am {w}"),
)

# Antwortmoeglichkeiten der Zusage-Zeile: ``(Wert, Beschriftung, Satz bejaht, Satz
# verneint)``. Der Chip wird aus dem Termin und diesem Satz gebaut, damit „hat
# geantwortet zu Konzert am 06.06.27" dasteht statt „Zusage: … — geantwortet".
# „ohne" ist die echte Zeile mit leerer Option; ihre Verneinung braucht ein eigenes
# Wort, „nicht keine Angabe gemacht" liest sich nicht.
ZUSAGE_ANTWORTEN = (
    ("1", "Zusage", "hat zugesagt", "hat nicht zugesagt"),
    ("2", "Absage", "hat abgesagt", "hat nicht abgesagt"),
    ("3", "Eventuell", "hat eventuell zugesagt", "hat nicht eventuell zugesagt"),
    ("ohne", "Keine Angabe", "hat keine Angabe gemacht", "hat eine Angabe gemacht"),
    ("beantwortet", "geantwortet", "hat geantwortet", "hat nicht geantwortet"),
)
ZUSAGE_LABELS = tuple((wert, label) for wert, label, _ja, _nein in ZUSAGE_ANTWORTEN)


# ------------------------------------------------------------------ Wertebauer


def _stimmen(werte, namen):
    labels = dict(User.STIMMEN)
    return ", ".join(labels.get(w, w) for w in werte)


def _zugang_q(operator, werte):
    return Q(is_active=True) if operator == "hat" else Q(is_active=False)


def _gruppen_q(operator, werte):
    treffer = Exists(Group.objects.filter(user=OuterRef("pk"), pk__in=werte))
    return treffer if operator == "in" else ~treffer


def _zusage_q(operator, werte):
    suche = {"person": OuterRef("pk"), "termin_id": werte[0]}
    antwort = werte[1]
    if antwort == "beantwortet":
        suche["option__in"] = ("1", "2", "3")
    elif antwort == "ohne":
        suche["option"] = ""
    else:
        suche["option"] = antwort
    treffer = Exists(Zusage.objects.filter(**suche))
    return treffer if operator == "hat" else ~treffer


def _satz_zusage(operator, werte, namen):
    """„hat geantwortet zu Konzert am 06.06.27" -- Termin und Antwort als Satz.

    Die Antwort bringt das Verb mit (``ZUSAGE_ANTWORTEN``), damit die Verneinung im
    richtigen Wort landet: „hat nicht zugesagt", aber „hat eine Angabe gemacht".
    """
    termin = (namen or {}).get(werte[0], werte[0])
    for wert, _label, bejaht, verneint in ZUSAGE_ANTWORTEN:
        if wert == werte[1]:
            return "%s zu %s" % (bejaht if operator == "hat" else verneint, termin)
    return termin


def _text_feld(key, label, feldnamen, recht=None):
    return Feld(
        key=key, label=label, art="text", operatoren=_TEXT,
        q=text_q(*feldnamen), werte_text=text_wert, recht=recht,
    )


def _datum_feld(key, label, feldname, mit_uhrzeit, recht=None):
    return Feld(
        key=key, label=label, art="datum", operatoren=_DATUM,
        q=datum_q(feldname, mit_uhrzeit), werte_text=datum_wert, recht=recht,
    )


FELDER = {
    "name": _text_feld("name", "Name", ("first_name", "last_name")),
    "stimme": Feld(
        key="stimme", label="Stimme", art="mehrfach", operatoren=_STIMME,
        q=wahl_q("stimme"), werte_text=_stimmen,
        texte={"auswahl_label": "Gewählte Stimmen", "vorrat_label": "Verfügbare Stimmen",
               "such_platzhalter": "Stimme suchen …", "leer_text": "Alle Stimmen"},
    ),
    "email": _text_feld("email", "E-Mail", ("email",), RECHT_VERWALTER),
    "xmpp": _text_feld("xmpp", "XMPP", ("xmpp",), RECHT_VERWALTER),
    "geburtstag": _datum_feld("geburtstag", "Geburtstag", "geburtstag", False, RECHT_VERWALTER),
    "last_login": _datum_feld("last_login", "Letzte Anmeldung", "last_login", True),
    "date_joined": _datum_feld("date_joined", "Eintritt", "date_joined", True),
    "strasse": _text_feld("strasse", "Straße", ("strasse",), RECHT_VERWALTER),
    "plz": _text_feld("plz", "PLZ", ("plz",), RECHT_VERWALTER),
    "ort": _text_feld("ort", "Ort", ("ort",), RECHT_VERWALTER),
    "telefon": _text_feld("telefon", "Telefon", ("telefon",), RECHT_VERWALTER),
    "telefon_job": _text_feld("telefon_job", "Telefon (Beruf)", ("telefon_job",), RECHT_VERWALTER),
    "telefon_mobil": _text_feld("telefon_mobil", "Mobil", ("telefon_mobil",), RECHT_VERWALTER),
    "telefon_job_mobil": _text_feld("telefon_job_mobil", "Mobil (Beruf)", ("telefon_job_mobil",), RECHT_VERWALTER),
    "fax": _text_feld("fax", "Fax", ("fax",), RECHT_VERWALTER),
    "zugang": Feld(
        key="zugang", label="Zugang", art="ohne", operatoren=_ZUGANG,
        q=_zugang_q, werte_text=lambda werte, namen: "", ohne_wert=True,
        recht=RECHT_VERWALTER,
    ),
    "gruppen": Feld(
        key="gruppen", label="Gruppen", art="mehrfach", operatoren=_GRUPPEN,
        q=_gruppen_q, werte_text=namens_wert,
        texte={"auswahl_label": "Gewählte Gruppen", "vorrat_label": "Verfügbare Gruppen",
               "such_platzhalter": "Gruppe suchen …", "leer_text": "Alle Gruppen"},
    ),
    "zusage": Feld(
        key="zusage", label="Zusage", art="zusage", operatoren=_HAT,
        q=_zusage_q, werte_text=namens_wert, namen_aus="termin",
        satz_bauer=_satz_zusage,
    ),
}

# Reihenfolge im Feld-Dropdown -- die Reihenfolge der Tabellenspalten.
FELD_REIHENFOLGE = (
    "name", "stimme", "email", "xmpp", "geburtstag", "last_login", "date_joined",
    "strasse", "plz", "ort", "telefon", "telefon_job", "telefon_mobil",
    "telefon_job_mobil", "fax", "zugang", "gruppen", "zusage",
)


# ------------------------------------------------------- Eigenheiten der Seite


def _eintraege(feld_key):
    """Die Auswahllisten, die der Server liefert: Gruppen, Stimmen, Termine."""
    if feld_key == "gruppen":
        return [{"wert": str(g.pk), "label": g.name} for g in Group.objects.order_by("id")]
    if feld_key == "stimme":
        return [{"wert": code, "label": label} for code, label in User.STIMMEN]
    if feld_key == "zusage":
        return _termine()
    return []


def _termine():
    """Die Termine fuer die Zusage-Auswahl. Nur solche mit Anwesenheitsabfrage --
    nur zu denen gibt es Zusagen, eine Auswahl ohne Treffer waere eine leere Zeile."""
    from .models import Termin

    return [
        {"wert": str(t.pk), "label": str(t)}
        for t in Termin.objects.filter(anwesenheit=True)
        .only("id", "kurz", "datum").order_by("-datum")
    ]


def zugang_egal(daten):
    """Hat der Verwalter die Zugangs-Vorgabe ausdruecklich abgewaehlt?

    ``unknown`` war der dritte Zustand des alten Schalters und bedeutete dasselbe --
    ohne diese Zeile schaltete die Vorgabe eine gemerkte „Egal"-Wahl wieder an.
    """
    return (daten.get("zugang") or "").strip() in (ZUGANG_EGAL, "unknown")


def _vorgabe(bedingungen, daten, kann_verwalten):
    """Dem Verwalter die uebliche Einschraenkung voranstellen: nur Konten mit Zugang.

    Ohne sie saehe er erstmals beendete Mitgliedschaften und gesperrte Konten. Ein
    ``?zugang=egal`` schaltet sie ab -- die Auskunft „ich will hier nicht
    einschraenken" laesst sich nicht als Bedingung ausdruecken, deshalb der Marker.
    """
    if not kann_verwalten or zugang_egal(daten):
        return bedingungen
    if any(b.feld == "zugang" for b in bedingungen):
        return bedingungen
    return [Bedingung("und", "zugang", "hat", ())] + list(bedingungen)


def _marker(feld_key, rest):
    """Faellt die letzte Zugangs-Bedingung weg, kommt ``zugang=egal`` mit: sonst
    haengte die Vorgabe sie beim naechsten Aufruf wieder an und der Chip waere nicht
    wegzubekommen."""
    if feld_key == "zugang" and not any(b.feld == "zugang" for b in rest):
        return {"zugang": ZUGANG_EGAL}
    return {}


def _traeger(daten):
    if zugang_egal(daten):
        return [("zugang", ZUGANG_EGAL)]
    return []


def _alt_parameter(daten):
    """Die festen Filterfelder von vor dem Baukasten.

    Sie muessen uebersetzt werden, obwohl ihre Felder aus der Oberflaeche
    verschwunden sind: ein gemerkter Filter im Cookie oder ein Lesezeichen traegt
    sie noch, und ungefiltert waere die Liste nicht wiederzuerkennen.
    """
    bedingungen = []

    def zahlen(name):
        return [w for w in daten.getlist(name) if w]

    gruppen = zahlen("gruppen")
    if gruppen:
        bedingungen.append(Bedingung("und", "gruppen", "in", tuple(gruppen)))
    nicht = zahlen("gruppen_nicht")
    if nicht:
        bedingungen.append(Bedingung("und", "gruppen", "nicht-in", tuple(nicht)))
    stimmen = zahlen("stimme")
    if stimmen:
        bedingungen.append(Bedingung("und", "stimme", "in", tuple(stimmen)))

    # zugang=true|false|unknown -- "unknown" war „Egal" und ergibt keine Bedingung.
    zugang = (daten.get("zugang") or "").strip()
    if zugang in ("true", "2"):
        bedingungen.append(Bedingung("und", "zugang", "hat", ()))
    elif zugang in ("false", "3"):
        bedingungen.append(Bedingung("und", "zugang", "hat-nicht", ()))

    # status + konzert waren ein Paar: der Termin allein filterte nicht. Der Sentinel
    # "0" hiess „keine Zeile" -- das ist jetzt „hat nicht geantwortet" und schliesst
    # auch eine Zeile mit leerer Angabe ein, wie es die Terminseite schon liest.
    konzert = (daten.get("konzert") or "").strip()
    status = (daten.get("status") or "").strip()
    if konzert and status == "0":
        bedingungen.append(
            Bedingung("und", "zusage", "hat-nicht", (konzert, "beantwortet"))
        )
    elif konzert and status:
        bedingungen.append(Bedingung("und", "zusage", "hat", (konzert, status)))

    return bedingungen


MITGLIEDER = Baukasten(
    felder=FELDER,
    reihenfolge=FELD_REIHENFOLGE,
    eintraege=_eintraege,
    vorgabe=_vorgabe,
    alt_parameter=_alt_parameter,
    marker=_marker,
    traeger=_traeger,
    zusaetze={
        # Die Zusage-Zeile braucht zwei Listen, hat aber nur einen Feldnamen.
        "zusage-antwort": [{"wert": w, "label": l} for w, l in ZUSAGE_LABELS],
    },
)
