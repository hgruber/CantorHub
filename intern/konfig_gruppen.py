"""Thematische Gruppierung der Konfigurationsschlüssel.

Die einzige Stelle, die weiß, welcher Schlüssel in welche Gruppe gehört. Bewusst
**ohne DB- und Model-Import**, damit sie mit ``SimpleTestCase`` testbar ist
(Projektregel: ein ``TestCase`` würde die Datenmigration ``0003_import`` gegen
die Legacy-MySQL fahren).

Die Zuordnung wird aus dem Schlüsselnamen abgeleitet — exakter Treffer schlägt
Präfix, das längste Präfix schlägt kürzere (einzige Kollision:
``MAIL_MAILINGLISTE_`` vs. ``MAIL_``). Ein Schlüssel ohne jeden Treffer landet
in der Restgruppe ``"sonstiges"``.
"""

from typing import NamedTuple


class Gruppe(NamedTuple):
    id: str
    titel: str
    hinweis: str
    keys: tuple[str, ...]      # exakte Schlüsselnamen
    praefixe: tuple[str, ...]  # Präfix-Zuordnungen


# Reihenfolge = Ausgabereihenfolge. „sonstiges" steht hier nicht drin — die
# Restgruppe wird in ``gruppiere()`` nur bei Bedarf ans Ende gehängt.
GRUPPEN: tuple[Gruppe, ...] = (
    Gruppe(
        id="verein",
        titel="Verein & Portal",
        hinweis="Name, Anschrift und öffentliche Startseite",
        keys=("VEREINSADRESSE", "VEREINS_URL"),
        praefixe=("VEREINSNAME", "HOMEPAGE_"),
    ),
    Gruppe(
        id="aufnahme",
        titel="Mitgliedsantrag & Dokumente",
        hinweis="Antragseingang und verlinkte Satzung sowie Beitragsordnung",
        keys=("ANTRAG_EMAIL", "SATZUNG_FILE_ID", "BEITRAGSORDNUNG_FILE_ID"),
        praefixe=(),
    ),
    Gruppe(
        id="mailversand",
        titel="E-Mail-Versand",
        hinweis="SMTP-Zugang und Absenderadresse",
        keys=(
            "DEFAULT_FROM_EMAIL",
            # Schalter (1/0), der MAIL_WILLKOMMEN/MAIL_REAKTIVIERT unterdrückt —
            # kein Text, deshalb auch heute schon in MAIL_NON_TEXT_KEYS des JS.
            "MAIL_BEI_AKTIVIERUNG",
        ),
        praefixe=("EMAIL_",),
    ),
    Gruppe(
        id="mailtexte",
        titel="E-Mail-Texte",
        hinweis="Textbausteine der automatischen E-Mails (Wiki-Markup)",
        keys=(),
        praefixe=("MAIL_",),
    ),
    Gruppe(
        id="mailingliste",
        titel="Auftritts-Mailingliste",
        hinweis="Öffentliche Auftritts-Erinnerungen ohne Mitgliederkonto",
        keys=(),
        praefixe=("MAILINGLISTE_", "MAIL_MAILINGLISTE_"),
    ),
    Gruppe(
        id="caldav",
        titel="Kalender (CalDAV)",
        hinweis="Kalender-Schnittstelle für Geräte",
        keys=(
            # Der alte ICS-Feed ist die Alternative ohne Login zum CalDAV-Kalender
            # und wird auf derselben Termine-Seite angeboten.
            "ICAL_SECRET",
        ),
        praefixe=("CALDAV_",),
    ),
    Gruppe(
        id="carddav",
        titel="Adressbuch (CardDAV)",
        hinweis="Adressbuch-Schnittstelle für Geräte",
        keys=(),
        praefixe=("CARDDAV_",),
    ),
    Gruppe(
        id="xmpp",
        titel="Forum-Chat (XMPP)",
        hinweis="Anbindung der Foren an ejabberd",
        keys=(),
        praefixe=("EJABBERD_",),
    ),
    Gruppe(
        id="portal",
        titel="Portal, Karte & Benachrichtigungen",
        hinweis="Upload-Grenze, Karten-Mittelpunkt und Benachrichtigungs-Intervalle",
        keys=("UPLOAD_MAX_MB", "PWRESET_MAX_PER_HOUR"),
        praefixe=("MAP_", "NOTIFY_"),
    ),
)

# VEREINS_URL baut zwar nur Links in E-Mails (get_base_url()), steht aber hier,
# weil wer die Portal-Adresse sucht, sie hier sucht. Der Gruppenhinweis nennt
# nur die Gruppenzweck, nicht diese Einzelnote — die steht bewusst im Code.

_SONSTIGE = Gruppe(
    id="sonstiges",
    titel="Sonstiges",
    hinweis="Schlüssel ohne bekannte Zuordnung",
    keys=(),
    praefixe=(),
)

_EXAKT: dict[str, str] = {k: g.id for g in GRUPPEN for k in g.keys}
# Längstes Präfix zuerst, damit MAIL_MAILINGLISTE_ vor MAIL_ zieht.
_PRAEFIXE: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((pfx, g.id) for g in GRUPPEN for pfx in g.praefixe),
        key=lambda pp: len(pp[0]),
        reverse=True,
    )
)


def zuordnung(key: str) -> str:
    """Liefert die Gruppen-ID für einen Schlüssel.

    Exakter Treffer schlägt Präfix, längstes Präfix schlägt kürzere, sonst
    ``"sonstiges"``.
    """
    gid = _EXAKT.get(key)
    if gid is not None:
        return gid
    for pfx, gid in _PRAEFIXE:
        if key.startswith(pfx):
            return gid
    return _SONSTIGE.id


def gruppiere(rows: list[dict]) -> list[dict]:
    """Sortiert ``rows`` (je mit ``key``) in die thematischen Gruppen.

    Gibt die Gruppen in Definitionsreihenfolge zurück, überspringt leere
    Gruppen und erhält die Eingabereihenfolge innerhalb einer Gruppe. Die
    Restgruppe „sonstiges" wird nur bei Bedarf ans Ende gehängt.
    """
    nach_id: dict[str, list[dict]] = {g.id: [] for g in GRUPPEN}
    nach_id[_SONSTIGE.id] = []
    for row in rows:
        nach_id[zuordnung(row["key"])].append(row)

    ergebnis: list[dict] = []
    for g in GRUPPEN:
        eintraege = nach_id[g.id]
        if not eintraege:
            continue
        ergebnis.append(
            {"id": g.id, "titel": g.titel, "hinweis": g.hinweis, "eintraege": eintraege}
        )
    rest = nach_id[_SONSTIGE.id]
    if rest:
        ergebnis.append(
            {"id": _SONSTIGE.id, "titel": _SONSTIGE.titel, "hinweis": _SONSTIGE.hinweis, "eintraege": rest}
        )
    return ergebnis