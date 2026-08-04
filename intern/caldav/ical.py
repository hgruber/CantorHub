"""iCalendar-Serialisierung — reine Funktionen, ohne ORM und ohne Konfiguration.

RFC 5545. Faltung und TEXT-Escaping kommen aus :mod:`intern.dav.text`; die
Regeln sind dieselben wie in der vCard.

Wie ``vcard.py`` importiert dieses Modul nichts aus ``intern.models`` und ruft
nie die Uhr: die Zeitzone und der Zeitstempel werden hereingereicht. Dadurch ist
die gesamte Serialisierung mit ``SimpleTestCase`` und ``SimpleNamespace``
prüfbar, ohne dass die Testdatenbank (und damit ``0003_import``) anläuft — und
``DTSTAMP`` lässt sich in einem Test festnageln.
"""

from datetime import timedelta, timezone

from ..dav.text import escape_text, liste, zeile
from ..dav import text as _text

__all__ = [
    "termin_daten", "geburtstag_daten", "vcalendar_text", "etag", "ctag",
    "uid_termin", "uid_geburtstag", "utc", "als_datum",
]

# Wird in den ETag gehasht und muss bei JEDER Änderung an der Serialisierung
# hochgezählt werden. Sonst behalten alle bereits synchronisierten Geräte ihre
# alten Termine für immer: der Feldinhalt ändert sich ja nicht, nur unsere
# Ausgabe — und woran sollte der Client das sonst merken?
_SERIALISIERUNG = "v1"

_PRODID = "-//CantorHub//CalDAV//DE"

# Termine ohne Uhrzeit stehen als 00:00 in der Datenbank: das Formular setzt
# datetime.min.time(), wenn nichts eingegeben wurde (intern/forms.py). Genau
# daran erkennen wir einen ganztägigen Termin.
_OHNE_UHRZEIT = (0, 0, 0)

# Dauer eines Termins ohne Endzeitpunkt — die Konvention des bisherigen
# ICS-Feeds, damit ein Wechsel des Abos nichts verschiebt.
_STANDARDDAUER = timedelta(hours=2)


def uid_termin(pk):
    """Stabile UID eines Termins.

    Der Primärschlüssel überlebt jede Umbenennung und Verlegung; er steht über
    ``/intern/termin/<pk>/`` ohnehin schon in der Adresszeile.
    """
    return f"cantorhub-termin-{pk}"


def uid_geburtstag(pk):
    """Stabile UID eines Geburtstags — der Primärschlüssel des Mitglieds."""
    return f"cantorhub-geburtstag-{pk}"


def utc(naiv, zone):
    """Naive Ortszeit → ``YYYYMMDDTHHMMSSZ``.

    ``USE_TZ`` ist in diesem Projekt aus, ``Termin.datum`` also naive Ortszeit.
    Die Umrechnung nach UTC ist der billigste Weg zu einer eindeutigen Angabe:
    ein ``VTIMEZONE`` wäre die Alternative, müsste aber die Umstellungsregeln
    mitliefern und wäre auf eine Zone festgenagelt.
    """
    return (
        naiv.replace(tzinfo=zone).astimezone(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )


def als_datum(d):
    """``date`` → ``YYYYMMDD`` für einen ``VALUE=DATE``-Wert."""
    return d.strftime("%Y%m%d")


def _ist_ganztaegig(datum, datum_bis):
    """Ob der Termin ohne Uhrzeit angelegt wurde.

    Beide Enden müssen auf Mitternacht liegen: sobald irgendwo eine Uhrzeit
    steht, ist es ein zeitgebundener Termin.
    """
    if (datum.hour, datum.minute, datum.second) != _OHNE_UHRZEIT:
        return False
    if datum_bis is None:
        return True
    return (datum_bis.hour, datum_bis.minute, datum_bis.second) == _OHNE_UHRZEIT


def _ort_zeile(ort):
    """``LOCATION`` aus einem ``Ort``: Name, Strasse, PLZ Ort."""
    if ort is None:
        return ""
    plz = getattr(ort, "plz", "") or ""
    stadt = getattr(ort, "ort", "") or ""
    teile = [
        getattr(ort, "name", "") or "",
        getattr(ort, "strasse", "") or "",
        f"{plz} {stadt}".strip(),
    ]
    return ", ".join(t for t in teile if t)


def termin_daten(termin, *, zone, basis_url="", standdauer=_STANDARDDAUER):
    """Rohdaten eines Termins als flaches ``dict``.

    ``termin`` muss nur Attribute anbieten, kein Django-Modell sein.

    ``standdauer`` ist die Dauer, die ein Termin ohne Endzeitpunkt bekommt —
    hereingereicht, damit dieses Modul selbst keine Konfiguration liest und
    mit ``SimpleTestCase`` testbar bleibt.

    Ganztägig heisst ``VALUE=DATE``, und dort ist ``DTEND`` **exklusiv**: der
    letzte Tag plus eins. „Letzter Tag" ist ``datum_bis`` einschliesslich —
    dieselbe Lesart wie in der Monatsansicht, wo ein mehrtägiger Termin bis
    einschliesslich ``datum_bis`` als Band gezeichnet wird.
    """
    pk = getattr(termin, "pk", None)
    datum = termin.datum
    datum_bis = getattr(termin, "datum_bis", None)
    ganztaegig = _ist_ganztaegig(datum, datum_bis)

    if ganztaegig:
        letzter = datum_bis.date() if datum_bis else datum.date()
        if letzter < datum.date():
            letzter = datum.date()
        beginn = als_datum(datum.date())
        ende = als_datum(letzter + timedelta(days=1))
    else:
        schluss = datum_bis if datum_bis and datum_bis > datum else datum + standdauer
        beginn = utc(datum, zone)
        ende = utc(schluss, zone)

    ort = getattr(termin, "ort", None)
    breite = getattr(ort, "breite", None)
    laenge = getattr(ort, "laenge", None)

    return {
        "uid": uid_termin(pk),
        "titel": getattr(termin, "kurz", "") or "",
        "beschreibung": (getattr(termin, "lang", "") or "").strip(),
        "ort": _ort_zeile(ort),
        "geo": (breite, laenge) if breite is not None and laenge is not None else None,
        "url": f"{basis_url}/intern/termin/{pk}/" if basis_url and pk else "",
        # Auftritte sind das, was die Startseite und die Auftritts-Mailingliste
        # öffentlich machen — die Unterscheidung ist auch auf dem Telefon nützlich.
        "kategorien": ["Auftritt" if getattr(termin, "repertoire", False) else "Termin"],
        "beginn": beginn,
        "ende": ende,
        "ganztaegig": ganztaegig,
        "wiederholung": "",
        "frei": False,
    }


def geburtstag_daten(mitglied, *, basis_url=""):
    """Rohdaten eines Geburtstags als jährlich wiederkehrender Ganztagstermin.

    ``DTSTART`` trägt das echte Geburtsjahr, damit Geräte das Alter mitzählen
    können; im Adressbuch steht dieselbe Angabe ohnehin schon als ``BDAY``.
    ``TRANSP:TRANSPARENT``, weil ein Geburtstag niemanden beschäftigt zeigt.
    """
    pk = getattr(mitglied, "pk", None)
    tag = mitglied.geburtstag
    name = " ".join(
        t for t in (getattr(mitglied, "first_name", "") or "",
                    getattr(mitglied, "last_name", "") or "") if t
    )
    return {
        "uid": uid_geburtstag(pk),
        "titel": f"{name} hat Geburtstag" if name else "Geburtstag",
        "beschreibung": "",
        "ort": "",
        "geo": None,
        "url": f"{basis_url}/intern/mitglied/{pk}/" if basis_url and pk else "",
        "kategorien": ["Geburtstag"],
        "beginn": als_datum(tag),
        "ende": als_datum(tag + timedelta(days=1)),
        "ganztaegig": True,
        "wiederholung": "FREQ=YEARLY",
        "frei": True,
    }


def vcalendar_text(daten, *, stand):
    """Serialisiert ein Daten-dict zu einem ``VCALENDAR`` mit einem ``VEVENT``.

    ``stand`` ist der Zeitpunkt für ``DTSTAMP`` als naive UTC-``datetime``. Alle
    Zeilen enden auf CRLF, auch die letzte — ein blosses ``\\n`` bringt strenge
    Parser aus dem Tritt.
    """
    datum_param = [("VALUE", "DATE")] if daten["ganztaegig"] else None

    z = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        zeile("UID", escape_text(daten["uid"])),
        zeile("DTSTAMP", stand.strftime("%Y%m%dT%H%M%SZ")),
        zeile("DTSTART", daten["beginn"], datum_param),
        zeile("DTEND", daten["ende"], datum_param),
        zeile("SUMMARY", escape_text(daten["titel"])),
    ]

    if daten.get("beschreibung"):
        z.append(zeile("DESCRIPTION", escape_text(daten["beschreibung"])))
    if daten.get("ort"):
        z.append(zeile("LOCATION", escape_text(daten["ort"])))
    if daten.get("geo"):
        # In iCalendar trennt ein Semikolon die beiden Zahlen; nichts zu escapen.
        z.append(zeile("GEO", f"{daten['geo'][0]};{daten['geo'][1]}"))
    if daten.get("kategorien"):
        z.append(zeile("CATEGORIES", liste(daten["kategorien"])))
    if daten.get("wiederholung"):
        z.append(zeile("RRULE", daten["wiederholung"]))
    if daten.get("url"):
        z.append(zeile("URL", daten["url"]))
    z.append(zeile("TRANSP", "TRANSPARENT" if daten.get("frei") else "OPAQUE"))
    z.append(zeile("STATUS", "CONFIRMED"))

    z.append("END:VEVENT")
    z.append("END:VCALENDAR")
    return "\r\n".join(z) + "\r\n"


def etag(daten):
    """Starker ETag eines Eintrags — Hash über die Feldwerte."""
    return _text.etag(daten, _SERIALISIERUNG)


ctag = _text.ctag
