"""Zeilenfaltung, TEXT-Escaping und die ETag-/CTag-Hashes.

Reine Funktionen ohne ORM und ohne Dateizugriff.

vCard 3.0 und iCalendar sind beide Nachfahren desselben Zeilenformats: gefaltet
wird auf 75 Oktette mit CRLF plus einem Leerzeichen (RFC 6350 §3.2,
RFC 5545 §3.1), und ein TEXT-Wert escaped Backslash, Semikolon, Komma und
Zeilenumbruch (RFC 6350 §3.4, RFC 5545 §3.3.11). Deshalb steht das hier einmal
statt zweimal.
"""

import hashlib

__all__ = [
    "escape_text", "strukturiert", "liste", "fold", "zeile",
    "kanonisch", "etag", "ctag",
]

# Die Fortsetzungszeile beginnt mit einem Leerzeichen, das selbst ein Oktett
# belegt, also bleiben dort nur 74 für Nutzlast.
_ZEILENLAENGE = 75


def escape_text(wert):
    """Escaped einen TEXT-Wert.

    Reihenfolge ist wichtig: der Backslash zuerst, sonst würden die gleich
    eingefügten Escapes ein zweites Mal escaped.
    """
    return (
        str(wert)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def strukturiert(komponenten):
    """Verbindet die Komponenten eines strukturierten Werts (``N``, ``ADR``).

    Jede Komponente wird einzeln escaped, die trennenden Semikola bleiben roh —
    genau andersherum wäre der Wert unlesbar.
    """
    return ";".join(escape_text(k or "") for k in komponenten)


def liste(eintraege):
    """Verbindet eine Werteliste (``CATEGORIES``, ``NICKNAME``).

    Kommas *innerhalb* eines Eintrags werden escaped, die Listentrenner nicht.
    """
    return ",".join(escape_text(e) for e in eintraege if e)


def fold(text):
    """Faltet eine Inhaltszeile auf 75 Oktette.

    Gezählt wird über die UTF-8-**Bytes**, nicht über Zeichen, und nie mitten in
    einer Mehrbyte-Folge geschnitten: ein „ä" im Nachnamen an der falschen
    Stelle zerlegt sonst die ganze Karte. Fortgesetzt wird mit CRLF plus genau
    einem Leerzeichen — der einzige Weg, den alle Clients verstehen; die
    vCard-2.1-Konvention mit Leerzeile ist hier keine Option.
    """
    roh = text.encode("utf-8")
    if len(roh) <= _ZEILENLAENGE:
        return text
    teile, start, grenze = [], 0, _ZEILENLAENGE
    while start < len(roh):
        ende = min(start + grenze, len(roh))
        # 0b10xxxxxx ist ein UTF-8-Folgebyte: zurück auf den Zeichenanfang.
        while ende > start and ende < len(roh) and (roh[ende] & 0xC0) == 0x80:
            ende -= 1
        teile.append(roh[start:ende].decode("utf-8"))
        start, grenze = ende, _ZEILENLAENGE - 1
    return "\r\n ".join(teile)


def zeile(name, wert, params=None):
    """Baut eine gefaltete Inhaltszeile ``NAME;PARAM=WERT:wert``.

    ``params`` ist eine Liste von ``(name, wert)``-Paaren; mehrwertige Parameter
    wie ``TYPE=HOME,VOICE`` übergibt man als fertigen String.
    """
    kopf = name
    for pname, pwert in params or []:
        kopf += f";{pname}={pwert}"
    return fold(f"{kopf}:{wert}")


def kanonisch(wert):
    """Stabile Textform eines Werts für den ETag-Hash."""
    if isinstance(wert, (list, tuple)):
        return "\x1e".join(kanonisch(w) for w in wert)
    return "" if wert is None else str(wert)


def etag(daten, serialisierung):
    """Starker ETag einer Ressource — Hash über die Feldwerte, nie über Blobs.

    Gehasht wird das **komplette** Daten-dict (sortiert, damit die Reihenfolge
    nichts ändert) statt einer gepflegten Feldliste: ein später ergänztes Feld
    kann so nicht vergessen werden. Für ein Foto steht stellvertretend seine
    Kennung darin, weshalb ein PROPFIND über eine ganze Sammlung keine einzige
    Datei öffnen muss.

    ``serialisierung`` ist die Formatversion des jeweiligen Serialisierers. Sie
    gehört in den Hash, weil sich sonst niemand ändert, wenn wir unsere Ausgabe
    ändern — die Feldwerte bleiben ja gleich.

    Verborgene Felder stehen gar nicht erst im dict, der ETag verrät also nicht,
    dass es sie gibt.
    """
    roh = "\x1f".join(
        [serialisierung]
        + [f"{k}={kanonisch(daten[k])}" for k in sorted(daten)]
    )
    return '"' + hashlib.sha256(roh.encode("utf-8")).hexdigest()[:32] + '"'


def ctag(paare):
    """CTag einer Sammlung aus ihren ``(pk, etag)``-Paaren.

    Ändert sich damit sowohl, wenn sich ein Eintrag ändert, als auch bei Zu- und
    Abgängen — die Primärschlüssel stecken mit im Hash.
    """
    roh = "|".join(f"{pk}:{tag}" for pk, tag in sorted(paare))
    return '"' + hashlib.sha256(roh.encode("utf-8")).hexdigest()[:32] + '"'
