"""WebDAV-XML: Multistatus bauen, PROPFIND- und REPORT-Rümpfe lesen.

Reine Funktionen ohne Datenbankzugriff — mit ``SimpleTestCase`` prüfbar.
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import NamedTuple

__all__ = [
    "NS_DAV", "NS_CARDDAV", "NS_CALDAV", "NS_CS", "qn", "element",
    "parse_body", "parse_propfind", "parse_report", "multistatus", "Report",
]

NS_DAV = "DAV:"
NS_CARDDAV = "urn:ietf:params:xml:ns:carddav"
NS_CALDAV = "urn:ietf:params:xml:ns:caldav"
NS_CS = "http://calendarserver.org/ns/"

# Ohne diese Registrierung schreibt ElementTree ns0/ns1/ns2 — gültig, aber die
# Rümpfe sind dann beim Debuggen mit curl kaum lesbar, und einzelne ältere
# Clients erwarten die üblichen Präfixe.
ET.register_namespace("D", NS_DAV)
ET.register_namespace("C", NS_CARDDAV)
ET.register_namespace("CAL", NS_CALDAV)
ET.register_namespace("CS", NS_CS)

# 256 KiB. Ein PROPFIND-Rumpf ist wenige hundert Byte gross; ein multiget über
# ein ganzes Adressbuch bleibt weit darunter.
_MAX_BODY = 256 * 1024

# Wurzelelement eines REPORT → Art. Beide Dienste benutzen denselben Parser;
# welche Art er beantwortet, entscheidet die aufrufende View.
_REPORT_ARTEN = {
    f"{{{NS_CARDDAV}}}addressbook-multiget": "multiget",
    f"{{{NS_CARDDAV}}}addressbook-query": "query",
    f"{{{NS_CALDAV}}}calendar-multiget": "multiget",
    f"{{{NS_CALDAV}}}calendar-query": "query",
}


class Report(NamedTuple):
    """Das Ergebnis von :func:`parse_report`.

    ``art``         ``"multiget"``, ``"query"`` oder ``None`` (unbekannt)
    ``props``       angefragte Property-Namen, ``None`` heisst „alles"
    ``hrefs``       die Ressourcen eines ``multiget``
    ``limit``       ``<C:limit><C:nresults>`` des CardDAV-Query
    ``komponenten`` Namen aus ``<CAL:comp-filter>`` ausser ``VCALENDAR``
    ``zeitraum``    ``(start, ende)`` aus ``<CAL:time-range>``, sonst ``None``
    """

    art: str | None
    props: list | None
    hrefs: list
    limit: int | None
    komponenten: tuple
    zeitraum: tuple | None


def qn(ns, name):
    """Qualifizierter Elementname, wie ElementTree ihn führt."""
    return f"{{{ns}}}{name}"


def parse_body(roh):
    """Parst einen Anfragerumpf; ``None`` bei leerem Rumpf.

    Bewusst die Standardbibliothek statt ``defusedxml`` oder ``lxml``:

    * XXE ist mit ``xml.etree`` nicht erreichbar — ElementTree registriert
      keinen ``ExternalEntityRefHandler``, und libexpat lädt von sich aus weder
      Dateien noch URLs. ``file:///etc/passwd`` läuft ins Leere.
    * „Billion Laughs" und quadratisches Aufblähen brauchen zwingend interne
      Entitäten, die nur in einer DTD stehen können. Wir weisen jeden Rumpf mit
      DOCTYPE ab; damit ist die Klasse geschlossen.
    * ``lxml`` wäre über python-docx im Image, aber eben nur transitiv. Eine
      Sicherheitsmassnahme darf nicht davon abhängen, welche Abhängigkeit
      python-docx morgen zieht.

    Dass die Rümpfe von angemeldeten Mitgliedern kommen, senkt das Risiko, hebt
    es aber nicht auf: ein übernommenes Konto wäre genau der Weg hinein.
    """
    if not roh or not roh.strip():
        return None
    if len(roh) > _MAX_BODY:
        raise ValueError("Rumpf zu gross")
    kopf = roh[:2048]
    if b"<!DOCTYPE" in kopf or b"<!ENTITY" in kopf:
        raise ValueError("DTD nicht erlaubt")
    try:
        return ET.fromstring(roh)
    except ET.ParseError as exc:
        raise ValueError(f"XML nicht lesbar: {exc}") from exc


def _prop_namen(wurzel):
    """Die angefragten Property-Namen unterhalb von ``<D:prop>``.

    ``None`` bedeutet „alles, was diese Ressource hat" — das gilt für
    ``<D:allprop/>``, ``<D:propname/>`` und einen leeren Rumpf.
    """
    if wurzel is None:
        return None
    if wurzel.find(qn(NS_DAV, "allprop")) is not None:
        return None
    if wurzel.find(qn(NS_DAV, "propname")) is not None:
        return None
    prop = wurzel.find(qn(NS_DAV, "prop"))
    if prop is None:
        return None
    return [kind.tag for kind in prop]


def parse_propfind(roh):
    """``PROPFIND``-Rumpf → Liste der Property-Namen oder ``None`` für „alles"."""
    return _prop_namen(parse_body(roh))


def _zeitpunkt(roh):
    """``YYYYMMDDTHHMMSSZ`` oder ``YYYYMMDD`` → naive UTC-``datetime``.

    Unlesbares gibt ``None`` — ein kaputter Filter darf den Abgleich nicht
    abbrechen, er wird dann eben nicht angewandt.
    """
    roh = (roh or "").strip()
    for muster in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(roh, muster)
        except ValueError:
            continue
    return None


def _komponenten(wurzel):
    """Die Komponentennamen aus ``<CAL:comp-filter>``.

    ``VCALENDAR`` fliegt raus: das ist immer der äussere Rahmen und sagt nichts
    darüber, wonach der Client sucht. Übrig bleibt ``VEVENT``, ``VTODO`` … —
    woran die View erkennt, ob sie überhaupt etwas anzubieten hat.
    """
    namen = []
    for el in wurzel.iter(qn(NS_CALDAV, "comp-filter")):
        name = (el.get("name") or "").strip().upper()
        if name and name != "VCALENDAR" and name not in namen:
            namen.append(name)
    return tuple(namen)


def parse_report(roh):
    """``REPORT``-Rumpf → :class:`Report`.

    ``<C:filter>`` des CardDAV-Query wird gelesen, aber nicht ausgewertet
    (siehe ``intern/carddav/__init__.py``); der CalDAV-Filter wird nur so weit
    ausgewertet, wie es billig ist: Komponentenname und Zeitraum.
    """
    wurzel = parse_body(roh)
    if wurzel is None:
        return Report(None, None, [], None, (), None)

    props = _prop_namen(wurzel)
    hrefs = [(h.text or "").strip() for h in wurzel.findall(qn(NS_DAV, "href"))]

    limit = None
    grenze = wurzel.find(qn(NS_CARDDAV, "limit"))
    if grenze is not None:
        n = grenze.find(qn(NS_CARDDAV, "nresults"))
        if n is not None and (n.text or "").strip().isdigit():
            limit = int(n.text.strip())

    zeitraum = None
    spanne = next(iter(wurzel.iter(qn(NS_CALDAV, "time-range"))), None)
    if spanne is not None:
        zeitraum = (_zeitpunkt(spanne.get("start")),
                    _zeitpunkt(spanne.get("end")))

    return Report(_REPORT_ARTEN.get(wurzel.tag), props, hrefs, limit,
                  _komponenten(wurzel), zeitraum)


def multistatus(eintraege):
    """Baut eine ``<D:multistatus>``-Antwort.

    ``eintraege`` ist eine Liste von ``(href, gefunden, fehlend)``:
    ``gefunden`` bildet Property-Namen auf einen Wert ab — ein String, ein
    ``Element`` oder eine Liste von Elementen —, ``fehlend`` ist die Liste der
    Namen, die es hier nicht gibt.

    Die fehlenden Properties werden ausdrücklich als zweites ``<D:propstat>``
    mit 404 gemeldet und nicht stillschweigend weggelassen. Das ist der
    häufigste Fehler selbstgebauter Server und die Stelle, an der iOS aussteigt.
    """
    wurzel = ET.Element(qn(NS_DAV, "multistatus"))
    for href, gefunden, fehlend in eintraege:
        antwort = ET.SubElement(wurzel, qn(NS_DAV, "response"))
        ET.SubElement(antwort, qn(NS_DAV, "href")).text = href

        if gefunden:
            ps = ET.SubElement(antwort, qn(NS_DAV, "propstat"))
            prop = ET.SubElement(ps, qn(NS_DAV, "prop"))
            for name, wert in gefunden.items():
                el = ET.SubElement(prop, name)
                if isinstance(wert, str):
                    el.text = wert
                elif isinstance(wert, list):
                    el.extend(wert)
                elif wert is not None:
                    el.append(wert)
            ET.SubElement(ps, qn(NS_DAV, "status")).text = "HTTP/1.1 200 OK"

        if fehlend:
            ps = ET.SubElement(antwort, qn(NS_DAV, "propstat"))
            prop = ET.SubElement(ps, qn(NS_DAV, "prop"))
            for name in fehlend:
                ET.SubElement(prop, name)
            ET.SubElement(ps, qn(NS_DAV, "status")).text = (
                "HTTP/1.1 404 Not Found"
            )

    return ET.tostring(wurzel, encoding="utf-8", xml_declaration=True)


def element(ns, tag, text=None, kinder=(), **attribute):
    """Kleiner Helfer für Property-Werte, die selbst XML sind.

    Der zweite Parameter heisst ``tag`` und nicht ``name``, weil ``name`` als
    *Attribut* gebraucht wird: ``element(CAL, "comp", name="VEVENT")``.
    """
    el = ET.Element(qn(ns, tag), {k: str(v) for k, v in attribute.items()})
    if text is not None:
        el.text = text
    for k in kinder:
        el.append(k)
    return el
