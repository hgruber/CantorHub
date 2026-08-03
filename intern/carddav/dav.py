"""WebDAV-XML: Multistatus bauen, PROPFIND- und REPORT-Rümpfe lesen.

Reine Funktionen ohne Datenbankzugriff — wie :mod:`~intern.carddav.vcard` mit
``SimpleTestCase`` prüfbar.
"""

import xml.etree.ElementTree as ET

__all__ = [
    "NS_DAV", "NS_CARDDAV", "NS_CS", "qn", "element",
    "parse_body", "parse_propfind", "parse_report", "multistatus",
]

NS_DAV = "DAV:"
NS_CARDDAV = "urn:ietf:params:xml:ns:carddav"
NS_CS = "http://calendarserver.org/ns/"

# Ohne diese Registrierung schreibt ElementTree ns0/ns1/ns2 — gültig, aber die
# Rümpfe sind dann beim Debuggen mit curl kaum lesbar, und einzelne ältere
# Clients erwarten die üblichen Präfixe.
ET.register_namespace("D", NS_DAV)
ET.register_namespace("C", NS_CARDDAV)
ET.register_namespace("CS", NS_CS)

# 256 KiB. Ein PROPFIND-Rumpf ist wenige hundert Byte gross; ein multiget über
# ein ganzes Adressbuch bleibt weit darunter.
_MAX_BODY = 256 * 1024


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


def parse_report(roh):
    """``REPORT``-Rumpf → ``(art, props, hrefs, limit)``.

    ``art`` ist ``"multiget"``, ``"query"`` oder ``None`` (unbekannter Report).
    ``<C:filter>`` wird gelesen, aber nicht ausgewertet — siehe Modul-Docstring
    des Pakets.
    """
    wurzel = parse_body(roh)
    if wurzel is None:
        return None, None, [], None

    props = _prop_namen(wurzel)
    hrefs = [(h.text or "").strip() for h in wurzel.findall(qn(NS_DAV, "href"))]

    limit = None
    grenze = wurzel.find(qn(NS_CARDDAV, "limit"))
    if grenze is not None:
        n = grenze.find(qn(NS_CARDDAV, "nresults"))
        if n is not None and (n.text or "").strip().isdigit():
            limit = int(n.text.strip())

    if wurzel.tag == qn(NS_CARDDAV, "addressbook-multiget"):
        art = "multiget"
    elif wurzel.tag == qn(NS_CARDDAV, "addressbook-query"):
        art = "query"
    else:
        art = None
    return art, props, hrefs, limit


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


def element(ns, name, text=None, kinder=(), **attribute):
    """Kleiner Helfer für Property-Werte, die selbst XML sind."""
    el = ET.Element(qn(ns, name), {k: str(v) for k, v in attribute.items()})
    if text is not None:
        el.text = text
    for k in kinder:
        el.append(k)
    return el
