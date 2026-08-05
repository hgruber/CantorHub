"""Der einzige Berührpunkt des CalDAV-Pakets mit Datenbank und Konfiguration.

Alles, was hier steht, lässt sich nur mit einer Testdatenbank prüfen — und die
gibt es in diesem Projekt nicht (die Migration ``0003_import`` bräuchte den
Altbestand auf dem MySQL-Server). Deshalb bleibt dieses Modul dünn und schiebt
jede Entscheidung, die sich rein rechnerisch treffen lässt, nach
:mod:`~intern.caldav.ical` — dort ist sie testbar.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils.timezone import now as jetzt_lokal

from ..app_settings import get_config, get_config_bool, get_config_int, get_vereinsname_lang, get_zeitzone
from . import ical

logger = logging.getLogger(__name__)

__all__ = [
    "Eintrag", "ARTEN", "eintraege", "ctag", "sammlung_name", "farbe",
    "geburtstage_aktiv", "zeitzone", "stand",
]

ARTEN = ("termine", "geburtstage")


class Eintrag(NamedTuple):
    """Eine Ressource der Sammlung.

    ``spanne`` ist ``(beginn, ende)`` als naive Ortszeit und dient allein dem
    ``time-range``-Filter des ``calendar-query``. Für wiederkehrende Einträge
    steht dort ``None``: ein jährlicher Geburtstag berührt jeden Zeitraum, eine
    Vorauswahl wäre schlicht falsch.
    """

    objekt: object
    daten: dict
    tag: str
    spanne: tuple | None


def zeitzone():
    """Die Zone, in der ``Termin.datum`` gemeint ist.

    ``USE_TZ`` ist aus, die Werte sind also naive Ortszeit — welche Ortszeit,
    sagt der ``ZEITZONE``-Konfigurationsschlüssel (Fallback ``settings.TIME_ZONE``).
    Ein ungültiger Wert fällt hier nochmals auf ``settings.TIME_ZONE`` zurück, damit
    ein verstellter Eintrag niemals den Kalender-Export abwürgt.
    """
    try:
        return ZoneInfo(get_zeitzone())
    except Exception:
        return ZoneInfo(settings.TIME_ZONE)


def stand():
    """Zeitpunkt für ``DTSTAMP``, als naive UTC-``datetime``."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def geburtstage_aktiv():
    return get_config_bool("CALDAV_GEBURTSTAGE", True)


def sammlung_name(art):
    """Anzeigename der Sammlung auf dem Gerät."""
    verein = get_vereinsname_lang() or "CantorHub"
    if art == "geburtstage":
        return get_config("CALDAV_GEBURTSTAGE_NAME") or f"{verein} – Geburtstage"
    return get_config("CALDAV_KALENDER_NAME") or f"{verein} – Termine"


def farbe():
    """``CS:calendar-color``; leer, wenn nichts eingestellt ist."""
    return get_config("CALDAV_FARBE") or ""


def _termine():
    """Alle Termine im ausgelieferten Zeitfenster.

    Keine Rechteprüfung: im Portal darf jedes angemeldete Mitglied jeden Termin
    sehen (``views/termine.py`` kennt für Termine keine Sichtbarkeitsregel).
    Nach vorn wird nicht begrenzt — ein Kalender, der in einem Jahr aufhört,
    wäre eine Überraschung.
    """
    from ..models import Termin

    tage = get_config_int("CALDAV_TAGE_RUECKWIRKEND", 365)
    grenze = jetzt_lokal() - timedelta(days=tage)
    return (
        Termin.objects.filter(datum__gte=grenze)
        .select_related("ort")
        .order_by("datum")
    )


def _geburtstagskinder():
    """Aktive Mitglieder mit sichtbarem Geburtsdatum.

    Dieselbe Regel wie in der Monatsansicht und wie ``carddav_sichtbar``:
    ``private_fields`` entscheidet, und zwar für alle gleich — **kein
    Admin-Bonus**. Ein Geburtstag, der im Portal verborgen ist, hat auf keinem
    Telefon etwas zu suchen, auch nicht auf dem eines Vorstandsmitglieds.
    """
    from ..models import User

    for u in (
        User.objects.filter(is_active=True, geburtstag__isnull=False)
        .order_by("last_name", "first_name", "pk")
    ):
        if "geburtstag" not in (u.private_fields or []):
            yield u


def _spanne(termin, ganztaegig, standdauer):
    """``(beginn, ende)`` eines Termins für den ``time-range``-Filter.

    Das Ende ist grosszügig gewählt — lieber einen Termin zu viel ausliefern als
    einen, den der Client dann nicht sieht: ohne ``datum_bis`` gilt die
    Standarddauer, und ein ganztägiger Termin reicht bis zum Ende seines letzten
    Tages.
    """
    beginn = termin.datum
    ende = termin.datum_bis if termin.datum_bis and termin.datum_bis > beginn else beginn
    if ganztaegig:
        ende += timedelta(days=1)
    elif ende == beginn:
        ende += standdauer
    return beginn, ende


def eintraege(art, *, basis_url):
    """Die Ressourcen einer Sammlung als Liste von :class:`Eintrag`.

    Eine Datenbankabfrage, keine Dateizugriffe — der ETag entsteht allein aus
    Feldwerten.
    """
    if art == "geburtstage":
        ergebnis = []
        for u in _geburtstagskinder():
            d = ical.geburtstag_daten(u, basis_url=basis_url)
            ergebnis.append(Eintrag(u, d, ical.etag(d), None))
        return ergebnis

    zone = zeitzone()
    standdauer = timedelta(hours=get_config_int("CALDAV_STANDARDDAUER_STUNDEN", 2))
    ergebnis = []
    for t in _termine():
        d = ical.termin_daten(t, zone=zone, basis_url=basis_url, standdauer=standdauer)
        ergebnis.append(
            Eintrag(t, d, ical.etag(d), _spanne(t, d["ganztaegig"], standdauer))
        )
    return ergebnis


def einzeln(art, eid, *, basis_url):
    """Ein einzelner Eintrag — oder ``None``.

    Läuft bewusst über :func:`eintraege` statt über eine eigene Abfrage: so
    gelten für die Einzelressource garantiert dieselben Regeln (Zeitfenster,
    verborgene Geburtstage) und sie trägt denselben ETag wie in der Liste. Das
    kostet eine Abfrage über die ganze Sammlung, und die ist billig — es wird
    keine Datei geöffnet.
    """
    for e in eintraege(art, basis_url=basis_url):
        if e.objekt.pk == eid:
            return e
    return None


def nach_zeitraum(liste, zeitraum):
    """Wendet den ``time-range``-Filter eines ``calendar-query`` an.

    Die Grenzen kommen in UTC, unsere Zeitstempel sind naive Ortszeit — erst
    umrechnen, dann überlappen lassen. Einträge ohne Zeitspanne (die
    wiederkehrenden Geburtstage) bleiben immer drin.
    """
    start, ende = zeitraum
    zone = zeitzone()

    def lokal(punkt):
        if punkt is None:
            return None
        return (
            punkt.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)
        )

    von, bis = lokal(start), lokal(ende)

    def passt(e):
        if e.spanne is None:
            return True
        beginn, schluss = e.spanne
        if bis is not None and beginn >= bis:
            return False
        if von is not None and schluss <= von:
            return False
        return True

    return [e for e in liste if passt(e)]


def ctag(liste):
    """CTag einer Sammlung aus dem Ergebnis von :func:`eintraege`."""
    return ical.ctag([(e.objekt.pk, e.tag) for e in liste])
