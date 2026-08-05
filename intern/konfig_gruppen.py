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

# Eingabewidget je Schlüssel — abgeleitet aus der Lese-Verwendung im Code, nicht aus
# dem Schlüsselnamen: ``get_config_bool`` → "bool", ``get_config_int`` → "int",
# einzeilige Werte (URL/Host/JID/E-Mail/Passwort/Secret/Farbe/Name/Komma-Liste/
# Uhrzeit) → "string", mehrzeilige Texte (Mail-Body, Homepage-Prosa, Adresse,
# Einwilligung) → "text", Werte aus einer festen Optionliste (IANA-Zeitzone) →
# "select" (die Optionen stehen in ``SELECT_OPTIONEN``). Die gespeicherten Werte
# bleiben Zeichenketten; nur das Widget beim Editieren passt zur Funktion.
FELDTYPEN: dict[str, str] = {
    # bool (gelesen via get_config_bool)
    "EMAIL_USE_TLS": "bool",
    "EMAIL_USE_SSL": "bool",
    "CARDDAV_AKTIV": "bool",
    "CARDDAV_FOTO": "bool",
    "CALDAV_AKTIV": "bool",
    "CALDAV_GEBURTSTAGE": "bool",
    "MAIL_BEI_AKTIVIERUNG": "bool",
    "TERMIN_BANNER_AKTIV": "bool",
    # int (gelesen via get_config_int — SATZUNG_FILE_ID / BEITRAGSORDNUNG_FILE_ID /
    # MAP_CENTER_ID sind PKs für FilerFile.objects.get / Ort.objects.get)
    "EJABBERD_BOT_PORT": "int",
    "EMAIL_PORT": "int",
    "UPLOAD_MAX_MB": "int",
    "MAP_CENTER_ID": "int",
    "MAP_DEFAULT_ZOOM": "int",
    "PWRESET_MAX_PER_HOUR": "int",
    "CARDDAV_AUTH_TTL": "int",
    "CARDDAV_MAX_FEHLVERSUCHE_PRO_STUNDE": "int",
    "CALDAV_TAGE_RUECKWIRKEND": "int",
    "CALDAV_AUTH_TTL": "int",
    "CALDAV_MAX_FEHLVERSUCHE_PRO_STUNDE": "int",
    "NOTIFY_POLL_MS": "int",
    "NOTIFY_DISMISS_MS": "int",
    "SATZUNG_FILE_ID": "int",
    "BEITRAGSORDNUNG_FILE_ID": "int",
    "MAILINGLISTE_INTERVALL_MIN": "int",
    "MAILINGLISTE_OPTIN_TAGE": "int",
    "MITGLIED_EINLADUNG_TAGE": "int",
    "MITGLIED_BESTAETIGUNG_TAGE": "int",
    "AENDERUNGSPROTOKOLL_AUFBEWAHRUNG_TAGE": "int",
    "DATEIVERSION_AUFBEWAHRUNG_TAGE": "int",
    "DATEIVERSION_AUFBEWAHRUNG_ANZAHL": "int",
    "ERINNERUNG_VERSAND_AUFBEWAHRUNG_TAGE": "int",
    "ICAL_TAGE_RUECKWIRKEND": "int",
    "CALDAV_STANDARDDAUER_STUNDEN": "int",
    "EJABBERD_API_TIMEOUT": "int",
    "EJABBERD_BOT_RESCAN_SECONDS": "int",
    "EJABBERD_BOT_RELAY_SECONDS": "int",
    # string (einzeilig; MAILINGLISTE_WOCHEN = Komma-Liste, MAILINGLISTE_VERSANDZEIT
    # = Uhrzeit HH:MM, BRAND_FARBE = Hex — type=color kann „leer" nicht abbilden)
    "EJABBERD_API_URL": "string",
    "EJABBERD_HOST": "string",
    "EJABBERD_MUC_SERVICE": "string",
    "EJABBERD_BOT_JID": "string",
    "EJABBERD_BOT_PASSWORD": "string",
    "ICAL_SECRET": "string",
    "EMAIL_HOST": "string",
    "EMAIL_HOST_USER": "string",
    "EMAIL_HOST_PASSWORD": "string",
    "DEFAULT_FROM_EMAIL": "string",
    "CARDDAV_ADRESSBUCH_NAME": "string",
    "CARDDAV_ORGANISATION": "string",
    "CALDAV_KALENDER_NAME": "string",
    "CALDAV_GEBURTSTAGE_NAME": "string",
    "VEREINSNAME": "string",
    "VEREINSNAME_LANG": "string",
    "VEREINSNAME_KURZ": "string",
    "BRAND_FARBE": "string",
    "ANTRAG_EMAIL": "string",
    "VEREINS_URL": "string",
    "MAILINGLISTE_WOCHEN": "string",
    "MAILINGLISTE_VERSANDZEIT": "string",
    "OSM_TILE_URL": "string",
    "OSM_NOMINATIM_URL": "string",
    "MAP_CENTER_LAT": "string",
    "MAP_CENTER_LNG": "string",
    "FILE_PREFIX": "string",
    "DSB_URL": "string",
    # text (mehrzeilig: Mail-Body, Homepage-Prosa, Adresse, Einwilligung)
    "VEREINSADRESSE": "text",
    "HOMEPAGE_UEBER_UNS": "text",
    "HOMEPAGE_AUFNAHME": "text",
    "MAIL_ANTRAG": "text",
    "MAIL_ANTRAG_ADMIN": "text",
    "MAIL_ANTRAG_ADMIN_MINDERJAEHRIG": "text",
    "MAIL_ANTRAG_ADMIN_FOERDER": "text",
    "MAIL_BESTAETIGUNG": "text",
    "MAIL_BESTAETIGUNG_BESTAETIGT": "text",
    "MAIL_EINLADUNG": "text",
    "MAIL_NEUES_PASSWORT": "text",
    "MAIL_WILLKOMMEN": "text",
    "MAIL_REAKTIVIERT": "text",
    "MAIL_RUNDMAIL": "text",
    "MAIL_FOOTER": "text",
    "MAILINGLISTE_TEXT": "text",
    "MAILINGLISTE_EINWILLIGUNG": "text",
    "MAIL_MAILINGLISTE_OPTIN": "text",
    "MAIL_MAILINGLISTE_WILLKOMMEN": "text",
    "MAIL_MAILINGLISTE_BEREITS_ANGEMELDET": "text",
    "MAIL_MAILINGLISTE_ERINNERUNG": "text",
    "HOSTING_ANBIETER_NAME": "text",
    "HOSTING_ANBIETER_ANSCHRIFT": "text",
    "DSB_NAME": "text",
    "DSB_ANSCHRIFT": "text",
    # select (Optionen aus SELECT_OPTIONEN — hier IANA-Zeitzonen)
    "ZEITZONE": "select",
}


# Optionlisten für ``select``-Typen — Schlüssel → ((Wert, Anzeige), …). Bewusst
# hartcodiert und DB-frei, damit es mit ``SimpleTestCase`` prüfbar ist. Werte sind
# IANA-Namen; die Gültigkeit testet ``KonfigTypenTest`` gegen
# ``zoneinfo.available_timezones()``.
SELECT_OPTIONEN: dict[str, tuple[tuple[str, str], ...]] = {
    "ZEITZONE": (
        ("Europe/Berlin", "Berlin (DE)"),
        ("Europe/Zurich", "Zürich (CH)"),
        ("Europe/Vienna", "Wien (AT)"),
        ("Europe/Amsterdam", "Amsterdam (NL)"),
        ("Europe/Brussels", "Brüssel (BE)"),
        ("Europe/Paris", "Paris (FR)"),
        ("Europe/Luxembourg", "Luxemburg (LU)"),
        ("Europe/Copenhagen", "Kopenhagen (DK)"),
        ("Europe/Stockholm", "Stockholm (SE)"),
        ("Europe/Oslo", "Oslo (NO)"),
        ("Europe/Helsinki", "Helsinki (FI)"),
        ("Europe/Warsaw", "Warschau (PL)"),
        ("Europe/Prague", "Prag (CZ)"),
        ("Europe/Rome", "Rom (IT)"),
        ("Europe/Madrid", "Madrid (ES)"),
        ("Europe/Lisbon", "Lissabon (PT)"),
        ("Europe/London", "London (UK)"),
        ("Europe/Dublin", "Dublin (IE)"),
        ("Atlantic/Canary", "Kanaren"),
        ("America/New_York", "New York (US-Ost)"),
        ("America/Los_Angeles", "Los Angeles (US-West)"),
        ("UTC", "UTC"),
    ),
}


def feldtyp(key: str) -> str:
    """Liefert das Eingabewidget (``bool``/``int``/``string``/``text``/``select``).

    Unbekannte Schlüssel bekommen ``text`` (Textarea) — das sicherste Widget, falls
    ein ad-hoc angelegter Schlüssel nicht in ``FELDTYPEN`` steht.
    """
    return FELDTYPEN.get(key, "text")


# Anzeigereihenfolge der Schlüssel innerhalb ihrer Gruppe — nicht alphabetisch,
# sondern nach Gesichtspunkten: beim Verein beginnt die URL (technische Basis),
# dann Name, Adresse, Homepage-Texte; bei Mailtexten der Mitglied-Lebenszyklus
# (Einladung → Antrag → Aktivierung → Bestätigung → Passwort → Rundmail → Footer);
# bei CalDAV/CardDAV der Schalter vor den Detailparametern. Ein Schlüssel ohne
# Eintrag hier fällt ans Ende seiner Gruppe (alphabetisch).
SCHLUESSEL_REIHENFOLGE: tuple[str, ...] = (
    # Verein & Portal — Basis zuerst, dann Namen, Anschrift, Homepage-Texte
    "VEREINS_URL", "VEREINSNAME", "VEREINSNAME_LANG", "VEREINSNAME_KURZ",
    "BRAND_FARBE",
    "VEREINSADRESSE", "HOMEPAGE_UEBER_UNS", "HOMEPAGE_AUFNAHME",
    # Mitgliedsantrag & Dokumente — Fristen, dann wohin gehen Anträge, dann die verlinkten Dokumente
    "MITGLIED_EINLADUNG_TAGE", "MITGLIED_BESTAETIGUNG_TAGE",
    "ANTRAG_EMAIL", "SATZUNG_FILE_ID", "BEITRAGSORDNUNG_FILE_ID",
    # Datenschutz-Texte — Hosting-Anbieter, dann Aufsichtsbehörde
    "HOSTING_ANBIETER_NAME", "HOSTING_ANBIETER_ANSCHRIFT",
    "DSB_NAME", "DSB_ANSCHRIFT", "DSB_URL",
    # E-Mail-Versand — SMTP-Verbindung, dann Absender, dann Global-Schalter
    "EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS", "EMAIL_USE_SSL", "DEFAULT_FROM_EMAIL", "MAIL_BEI_AKTIVIERUNG",
    # E-Mail-Texte — Mitglied-Lebenszyklus
    "MAIL_EINLADUNG", "MAIL_ANTRAG", "MAIL_ANTRAG_ADMIN",
    "MAIL_ANTRAG_ADMIN_MINDERJAEHRIG", "MAIL_ANTRAG_ADMIN_FOERDER",
    "MAIL_WILLKOMMEN", "MAIL_REAKTIVIERT",
    "MAIL_BESTAETIGUNG", "MAIL_BESTAETIGUNG_BESTAETIGT",
    "MAIL_NEUES_PASSWORT", "MAIL_RUNDMAIL", "MAIL_FOOTER",
    # Auftritts-Mailingliste — Timing-Parameter, dann Formular-Texte, dann Mailtexte
    "MAILINGLISTE_WOCHEN", "MAILINGLISTE_VERSANDZEIT", "MAILINGLISTE_INTERVALL_MIN",
    "MAILINGLISTE_OPTIN_TAGE", "MAILINGLISTE_TEXT", "MAILINGLISTE_EINWILLIGUNG",
    "MAIL_MAILINGLISTE_OPTIN", "MAIL_MAILINGLISTE_WILLKOMMEN",
    "MAIL_MAILINGLISTE_BEREITS_ANGEMELDET", "MAIL_MAILINGLISTE_ERINNERUNG",
    # Kalender (CalDAV) — Schalter, Namen, Zeitraum, Auth, ICS-Alternative
    "CALDAV_AKTIV", "CALDAV_KALENDER_NAME", "CALDAV_GEBURTSTAGE",
    "CALDAV_GEBURTSTAGE_NAME", "CALDAV_TAGE_RUECKWIRKEND",
    "CALDAV_STANDARDDAUER_STUNDEN",
    "CALDAV_AUTH_TTL", "CALDAV_MAX_FEHLVERSUCHE_PRO_STUNDE",
    "ICAL_TAGE_RUECKWIRKEND", "ICAL_SECRET",
    # Adressbuch (CardDAV) — Schalter, Namen, Foto, Auth
    "CARDDAV_AKTIV", "CARDDAV_ADRESSBUCH_NAME", "CARDDAV_ORGANISATION",
    "CARDDAV_FOTO", "CARDDAV_AUTH_TTL", "CARDDAV_MAX_FEHLVERSUCHE_PRO_STUNDE",
    # Forum-Chat (XMPP) — Server, dann Bot
    "EJABBERD_HOST", "EJABBERD_MUC_SERVICE", "EJABBERD_API_URL",
    "EJABBERD_API_TIMEOUT",
    "EJABBERD_BOT_JID", "EJABBERD_BOT_PASSWORD", "EJABBERD_BOT_PORT",
    "EJABBERD_BOT_RESCAN_SECONDS", "EJABBERD_BOT_RELAY_SECONDS",
    # Portal, Karte & Benachrichtigungen — Zeitzone, Limits, Karte, OSM-Server, Benachrichtigungen
    "ZEITZONE",
    "UPLOAD_MAX_MB", "PWRESET_MAX_PER_HOUR", "MAP_CENTER_ID", "MAP_DEFAULT_ZOOM",
    "MAP_CENTER_LAT", "MAP_CENTER_LNG", "OSM_TILE_URL", "OSM_NOMINATIM_URL",
    "NOTIFY_POLL_MS", "NOTIFY_DISMISS_MS", "TERMIN_BANNER_AKTIV", "FILE_PREFIX",
    # Aufbewahrung & Bereinigung — Löschfristen der Cleanup-Jobs
    "AENDERUNGSPROTOKOLL_AUFBEWAHRUNG_TAGE", "DATEIVERSION_AUFBEWAHRUNG_TAGE",
    "DATEIVERSION_AUFBEWAHRUNG_ANZAHL", "ERINNERUNG_VERSAND_AUFBEWAHRUNG_TAGE",
)
_REIHENFOLGE_INDEX: dict[str, int] = {k: i for i, k in enumerate(SCHLUESSEL_REIHENFOLGE)}
_REIHENFOLGE_ENDE = len(SCHLUESSEL_REIHENFOLGE)


def _sortierschluessel(key: str) -> tuple:
    """Position in ``SCHLUESSEL_REIHENFOLGE``; unbekannte Schlüssel ans Ende."""
    return (_REIHENFOLGE_INDEX.get(key, _REIHENFOLGE_ENDE), key)


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
        hinweis="Name, Anschrift, Akzentfarbe und öffentliche Startseite",
        keys=("VEREINSADRESSE", "VEREINS_URL", "BRAND_FARBE"),
        praefixe=("VEREINSNAME", "HOMEPAGE_"),
    ),
    Gruppe(
        id="aufnahme",
        titel="Mitgliedsantrag, Fristen & Dokumente",
        hinweis="Einladungs- und Bestätigungsfristen, Antragseingang und verlinkte "
        "Satzung sowie Beitragsordnung",
        keys=(
            "MITGLIED_EINLADUNG_TAGE",
            "MITGLIED_BESTAETIGUNG_TAGE",
            "ANTRAG_EMAIL",
            "SATZUNG_FILE_ID",
            "BEITRAGSORDNUNG_FILE_ID",
        ),
        praefixe=(),
    ),
    Gruppe(
        id="datenschutz",
        titel="Datenschutz-Texte",
        hinweis="Hosting-Anbieter und Aufsichtsbehörde in der Datenschutzerklärung",
        keys=(
            "HOSTING_ANBIETER_NAME",
            "HOSTING_ANBIETER_ANSCHRIFT",
            "DSB_NAME",
            "DSB_ANSCHRIFT",
            "DSB_URL",
        ),
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
            "ICAL_TAGE_RUECKWIRKEND",
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
        hinweis="Upload-Grenze, Karten-Mittelpunkt, OSM-Server, "
        "Benachrichtigungs-Intervalle und Terminerinnerung",
        keys=(
            "ZEITZONE",
            "UPLOAD_MAX_MB",
            "PWRESET_MAX_PER_HOUR",
            "OSM_TILE_URL",
            "OSM_NOMINATIM_URL",
            "TERMIN_BANNER_AKTIV",
            "FILE_PREFIX",
        ),
        praefixe=("MAP_", "NOTIFY_"),
    ),
    Gruppe(
        id="aufbewahrung",
        titel="Aufbewahrung & Bereinigung",
        hinweis="Löschfristen der Cleanup-Jobs (Änderungsprotokoll, Dateiversionen, "
        "Versand-Marker)",
        keys=(
            "AENDERUNGSPROTOKOLL_AUFBEWAHRUNG_TAGE",
            "DATEIVERSION_AUFBEWAHRUNG_TAGE",
            "DATEIVERSION_AUFBEWAHRUNG_ANZAHL",
            "ERINNERUNG_VERSAND_AUFBEWAHRUNG_TAGE",
        ),
        praefixe=(),
    ),
)

# VEREINS_URL baut zwar nur Links in E-Mails (get_base_url()), steht aber hier,
# weil wer die Portal-Adresse sucht, sie hier sucht. Der Gruppenhinweis nennt
# nur die Gruppenzweck, nicht diese Einzelnote — die steht bewusst im Code.

_SONSTIGE = Gruppe(
    id="sonstiges",
    titel="Zusätzliche Parameter",
    hinweis="Manuell angelegte Schlüssel ohne feste Zuordnung — hier gefahrlos löschbar",
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
        # Kopie mit angereichertem ``typ``/``manuell`` — der Eingabe-dict wird nicht mutiert.
        gid = zuordnung(row["key"])
        typ = feldtyp(row["key"])
        eintrag = {
            **row,
            "typ": typ,
            "manuell": gid == _SONSTIGE.id,
            "optionen": SELECT_OPTIONEN.get(row["key"], ()) if typ == "select" else (),
        }
        nach_id[gid].append(eintrag)

    ergebnis: list[dict] = []
    for g in GRUPPEN:
        eintraege = nach_id[g.id]
        if not eintraege:
            continue
        eintraege.sort(key=lambda e: _sortierschluessel(e["key"]))
        ergebnis.append(
            {"id": g.id, "titel": g.titel, "hinweis": g.hinweis, "eintraege": eintraege}
        )
    rest = nach_id[_SONSTIGE.id]
    if rest:
        rest.sort(key=lambda e: _sortierschluessel(e["key"]))
        ergebnis.append(
            {"id": _SONSTIGE.id, "titel": _SONSTIGE.titel, "hinweis": _SONSTIGE.hinweis, "eintraege": rest}
        )
    return ergebnis