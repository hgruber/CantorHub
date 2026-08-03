"""vCard-3.0-Serialisierung — reine Funktionen, ohne ORM und ohne Dateizugriff.

Version 3.0 und nicht 4.0: iOS-Kontakte arbeitet damit historisch am
zuverlässigsten, ``PHOTO;ENCODING=b`` ist auf beiden Zielplattformen erprobt
(die 4.0-Schreibweise mit ``data:``-URI nicht), und ``IMPP`` ist über RFC 4770
auch für 3.0 definiert. Für einen read-only Dienst gibt es keinen Grund für 4.0.

Dieses Modul importiert bewusst nichts aus ``intern.models``. Welche Felder ein
Betrachter sehen darf, entscheidet das Callable ``sichtbar`` — die View reicht
die echte Regel herein, ein Test ein einfaches Mengen-Lookup. Dadurch ist die
gesamte Serialisierung mit ``SimpleTestCase`` und ``SimpleNamespace`` prüfbar,
ohne dass die Testdatenbank (und damit die Migration ``0003_import``) anläuft.
"""

import base64
import hashlib

__all__ = [
    "escape_text", "strukturiert", "liste", "fold", "zeile",
    "kontakt_daten", "vcard_text", "etag", "ctag", "uid_fuer",
]

# Wird in den ETag gehasht und muss bei JEDER Änderung an der Serialisierung
# hochgezählt werden. Sonst behalten alle bereits synchronisierten Clients ihre
# alten Karten für immer: der Feldinhalt ändert sich ja nicht, nur unsere
# Ausgabe — und woran sollte der Client das sonst merken?
_SERIALISIERUNG = "v1"

# RFC 6350 §3.2. Die Fortsetzungszeile beginnt mit einem Leerzeichen, das selbst
# ein Oktett belegt, also bleiben dort nur 74 für Nutzlast.
_ZEILENLAENGE = 75


def escape_text(wert):
    """Escaped einen TEXT-Wert nach RFC 6350 §3.4.

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
    """Faltet eine Inhaltszeile auf 75 Oktette (RFC 6350 §3.2).

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


def uid_fuer(pk):
    """Stabile UID einer Mitgliedskarte.

    Der Primärschlüssel ist der einzige Anker, der Namens-, Stimm- und
    Benutzernamensänderungen übersteht — und er ist über ``/intern/mitglied/<pk>/``
    ohnehin schon sichtbar.
    """
    return f"cantorhub-mitglied-{pk}"


# Reihenfolge der Telefonnummern; die erste vorhandene bekommt PREF.
_TELEFON_FELDER = [
    ("telefon", "HOME,VOICE"),
    ("telefon_mobil", "CELL,VOICE"),
    ("telefon_job", "WORK,VOICE"),
    ("telefon_job_mobil", "WORK,CELL"),
    ("fax", "HOME,FAX"),
]

# Adressfelder hängen aneinander: ist eines davon verborgen, entfällt auch GEO.
_ADRESS_FELDER = ("strasse", "plz", "ort")


def _wert(mitglied, feld, sichtbar):
    """Feldwert, sofern gesetzt und für den Abrufenden sichtbar — sonst ``""``."""
    if not sichtbar(feld):
        return ""
    return getattr(mitglied, feld, None) or ""


def kontakt_daten(mitglied, sichtbar, *, organisation="", basis_url="",
                  stimme_label="", foto_kennung=""):
    """Baut die Rohdaten einer Karte als flaches ``dict``.

    ``mitglied`` muss nur Attribute anbieten, kein Django-Modell sein.
    ``sichtbar`` ist ein Callable ``feld -> bool``; verborgene und leere Felder
    führen dazu, dass die zugehörige Property später vollständig entfällt — eine
    leere ``TEL;TYPE=CELL:`` legt auf Android einen leeren Kontakteintrag an.
    """
    vorname = getattr(mitglied, "first_name", "") or ""
    nachname = getattr(mitglied, "last_name", "") or ""
    pk = getattr(mitglied, "pk", None)

    telefone = []
    for feld, typen in _TELEFON_FELDER:
        nummer = _wert(mitglied, feld, sichtbar)
        if nummer:
            telefone.append((typen, str(nummer)))
    if telefone:
        typen, nummer = telefone[0]
        telefone[0] = (typen + ",PREF", nummer)

    strasse = _wert(mitglied, "strasse", sichtbar)
    plz = _wert(mitglied, "plz", sichtbar)
    ort = _wert(mitglied, "ort", sichtbar)
    adresse = (strasse, plz, ort) if (strasse or plz or ort) else None

    # GEO nur, wenn die Anschrift vollständig sichtbar ist. Beim Speichern nullt
    # das Formular die Koordinaten bereits, sobald ein Adressfeld verborgen wird
    # (ADDRESS_TRIGGER_FIELDS) — ein Import am Formular vorbei täte das nicht,
    # und aus Breite/Länge liesse sich die Anschrift zurückrechnen.
    breite = getattr(mitglied, "breite", None)
    laenge = getattr(mitglied, "laenge", None)
    geo = None
    if breite is not None and laenge is not None and all(
        sichtbar(f) for f in _ADRESS_FELDER
    ):
        geo = (breite, laenge)

    geburtstag = ""
    roh_geburtstag = _wert(mitglied, "geburtstag", sichtbar)
    if roh_geburtstag:
        geburtstag = getattr(roh_geburtstag, "isoformat", lambda: str(roh_geburtstag))()

    notiz_teile = []
    text = getattr(mitglied, "text", "") or ""
    if text.strip():
        notiz_teile.append(text.strip())
    eintritt = getattr(mitglied, "date_joined", None)
    if eintritt is not None:
        notiz_teile.append(f"Mitglied seit {eintritt.year}")

    kategorien = [k for k in (organisation, stimme_label) if k]

    return {
        "uid": uid_fuer(pk),
        "vorname": vorname,
        "nachname": nachname,
        "fn": " ".join(t for t in (vorname, nachname) if t),
        "nickname": getattr(mitglied, "username", "") or "",
        "organisation": organisation,
        "titel": stimme_label,
        "kategorien": kategorien,
        "email": _wert(mitglied, "email", sichtbar),
        "telefone": telefone,
        "adresse": adresse,
        "geo": geo,
        "geburtstag": geburtstag,
        "xmpp": _wert(mitglied, "xmpp", sichtbar),
        "notiz": "\n".join(notiz_teile),
        "url": f"{basis_url}/intern/mitglied/{pk}/" if basis_url and pk else "",
        "foto_kennung": foto_kennung,
    }


def vcard_text(daten, foto=None):
    """Serialisiert ein ``kontakt_daten``-dict zu einer vCard 3.0.

    ``foto`` ist ``(mime, bytes)`` oder ``None``. Alle Zeilen enden auf CRLF,
    auch die letzte — ein blosses ``\\n`` bringt strenge Parser aus dem Tritt.
    """
    z = ["BEGIN:VCARD", "VERSION:3.0", "PRODID:-//CantorHub//DE"]

    z.append(zeile("UID", escape_text(daten["uid"])))
    z.append(zeile("N", strukturiert(
        [daten["nachname"], daten["vorname"], "", "", ""])))
    z.append(zeile("FN", escape_text(daten["fn"])))

    if daten.get("nickname"):
        z.append(zeile("NICKNAME", escape_text(daten["nickname"])))
    if daten.get("organisation"):
        z.append(zeile("ORG", strukturiert([daten["organisation"]])))
    if daten.get("titel"):
        z.append(zeile("TITLE", escape_text(daten["titel"])))
    if daten.get("kategorien"):
        # DAVx5 bildet CATEGORIES auf Android-Kontaktgruppen ab.
        z.append(zeile("CATEGORIES", liste(daten["kategorien"])))
    if daten.get("email"):
        z.append(zeile("EMAIL", escape_text(daten["email"]),
                       [("TYPE", "INTERNET,HOME,PREF")]))

    for typen, nummer in daten.get("telefone") or []:
        z.append(zeile("TEL", escape_text(nummer), [("TYPE", typen)]))

    if daten.get("adresse"):
        strasse, plz, ort = daten["adresse"]
        # ADR-Komponenten: Postfach;Zusatz;Strasse;Ort;Region;PLZ;Land
        z.append(zeile("ADR", strukturiert(
            ["", "", strasse, ort, "", plz, ""]), [("TYPE", "HOME")]))
    if daten.get("geo"):
        # In 3.0 trennt ein Semikolon die beiden Zahlen; nichts zu escapen.
        z.append(zeile("GEO", f"{daten['geo'][0]};{daten['geo'][1]}"))
    if daten.get("geburtstag"):
        z.append(zeile("BDAY", daten["geburtstag"]))
    if daten.get("xmpp"):
        jid = daten["xmpp"]
        # X-SERVICE-TYPE versteht iOS, X-JABBER die älteren Android-Importer.
        z.append(zeile("IMPP", f"xmpp:{jid}",
                       [("X-SERVICE-TYPE", "XMPP"), ("TYPE", "HOME")]))
        z.append(zeile("X-JABBER", escape_text(jid)))
    if daten.get("notiz"):
        z.append(zeile("NOTE", escape_text(daten["notiz"])))
    if daten.get("url"):
        z.append(zeile("URL", daten["url"]))

    if foto:
        mime, rohdaten = foto
        typ = mime.rsplit("/", 1)[-1].upper()
        z.append(zeile("PHOTO", base64.b64encode(rohdaten).decode("ascii"),
                       [("ENCODING", "b"), ("TYPE", typ)]))

    z.append("END:VCARD")
    return "\r\n".join(z) + "\r\n"


def _kanonisch(wert):
    """Stabile Textform eines Werts für den ETag-Hash."""
    if isinstance(wert, (list, tuple)):
        return "\x1e".join(_kanonisch(w) for w in wert)
    return "" if wert is None else str(wert)


def etag(daten):
    """Starker ETag einer Karte — Hash über die Feldwerte, nie über Fotobytes.

    Gehasht wird das komplette ``kontakt_daten``-dict (sortiert, damit die
    Reihenfolge nichts ändert) statt einer gepflegten Feldliste: ein später
    ergänztes Feld kann so nicht vergessen werden. ``foto_kennung`` steht darin
    stellvertretend für das Bild, weshalb ein PROPFIND über alle Kontakte keine
    einzige Bilddatei öffnen muss.

    Verborgene Felder stehen gar nicht erst im dict, der ETag verrät also nicht,
    dass es sie gibt.
    """
    roh = "\x1f".join(
        [_SERIALISIERUNG]
        + [f"{k}={_kanonisch(daten[k])}" for k in sorted(daten)]
    )
    return '"' + hashlib.sha256(roh.encode("utf-8")).hexdigest()[:32] + '"'


def ctag(paare):
    """CTag einer Sammlung aus ihren ``(pk, etag)``-Paaren.

    Ändert sich damit sowohl, wenn sich eine Karte ändert, als auch bei Zu- und
    Abgängen — die Primärschlüssel stecken mit im Hash.
    """
    roh = "|".join(f"{pk}:{tag}" for pk, tag in sorted(paare))
    return '"' + hashlib.sha256(roh.encode("utf-8")).hexdigest()[:32] + '"'
