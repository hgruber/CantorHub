"""Platzhalter in Wiki-Artikeln: ``{VEREINS_URL}``, ``{XMPP_ADRESSE}`` …

Die Hilfe-Artikel (``intern/hilfe/``) nennen die Werte, die ein Mitglied in
sein Telefon tippen muss. Diese hängen von der Installation und vom Leser ab,
deshalb stehen im Artikel Platzhalter, die erst beim Anzeigen ersetzt werden.

Nur die Namen in ``BESCHREIBUNG`` werden ersetzt. Ein beliebiger
``Konfiguration``-Schlüssel ginge nicht: ``{EMAIL_HOST_PASSWORD}`` stünde dann
für jeden Leser im Klartext da. Alles andere in geschweiften Klammern —
``{abstimmung:…}``, ein unbekannter Name — bleibt unverändert.

Oben die reine Ersetzung (``SimpleTestCase``), unten der DB-Teil.
"""

import html
import re
from urllib.parse import urlsplit

# Name → Bedeutung; die Bedeutung zeigt der Artikel „Hilfe:Wiki“.
BESCHREIBUNG = {
    "VEREINS_URL": "Adresse des Portals, z. B. https://portal.example.org",
    "SERVER": "nur der Rechnername des Portals, z. B. portal.example.org",
    "CALDAV_URL": "Adresse für Kalender-Apps (CalDAV)",
    "CARDDAV_URL": "Adresse für Adressbuch-Apps (CardDAV)",
    "ICAL_URL": "Abo-Adresse des Terminkalenders (ohne Passwort)",
    "WEBCAL_URL": "dieselbe Abo-Adresse mit webcal:// — öffnet direkt die Kalender-App",
    "KALENDER_NAME": "Name des Terminkalenders auf dem Telefon",
    "GEBURTSTAGE_NAME": "Name des Geburtstagskalenders auf dem Telefon",
    "ADRESSBUCH_NAME": "Name des Adressbuchs auf dem Telefon",
    "CALDAV_STATUS": "„eingeschaltet“ oder „noch nicht eingeschaltet“",
    "CARDDAV_STATUS": "„eingeschaltet“ oder „noch nicht eingeschaltet“",
    "XMPP_STATUS": "„eingeschaltet“ oder „noch nicht eingeschaltet“",
    "XMPP_DOMAIN": "Domain des Chat-Servers",
    "XMPP_ADRESSE": "die Chat-Adresse des Lesers",
    "BENUTZERNAME": "der Benutzername des Lesers",
    "VEREINSNAME": "Name des Vereins",
    "VEREINSNAME_LANG": "langer Vereinsname",
    "VEREINSNAME_KURZ": "kurzer Vereinsname",
}

# Was dasteht, wenn ein Wert in dieser Installation fehlt.
FEHLT = "(noch nicht eingerichtet)"

MUSTER = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")

EIN = "eingeschaltet"
AUS = "noch nicht eingeschaltet"


def ersetzen(zeile, werte):
    """``{NAME}`` in einer bereits HTML-escapten Zeile ersetzen.

    ``werte`` ist ein Aufrufbares ohne Argument, das das Wertewörterbuch
    liefert — erst gerufen, wenn die Zeile wirklich einen bekannten Namen
    enthält, damit Artikel ohne Platzhalter die Datenbank nicht berühren.
    """
    if "{" not in zeile:
        return zeile

    def _wert(m):
        name = m.group(1)
        if name not in BESCHREIBUNG:
            return m.group(0)
        return html.escape(werte().get(name) or FEHLT)

    return MUSTER.sub(_wert, zeile)


def server_aus_url(url):
    """``https://portal.example.org:8443/`` → ``portal.example.org:8443``."""
    teile = urlsplit(url or "")
    return teile.netloc or ""


def werte_berechnen(*, basis, ical_pfad, xmpp_domain, xmpp_adresse, benutzername,
                    caldav_aktiv, carddav_aktiv, namen):
    """Die Werte aus ihren Zutaten — ohne DB, deshalb testbar."""
    server = server_aus_url(basis)
    werte = {
        "VEREINS_URL": basis,
        "SERVER": server,
        "CALDAV_URL": f"{basis}/caldav/" if basis else "",
        "CARDDAV_URL": f"{basis}/carddav/" if basis else "",
        "ICAL_URL": f"{basis}{ical_pfad}" if basis and ical_pfad else "",
        "WEBCAL_URL": f"webcal://{server}{ical_pfad}" if server and ical_pfad else "",
        "CALDAV_STATUS": EIN if caldav_aktiv else AUS,
        "CARDDAV_STATUS": EIN if carddav_aktiv else AUS,
        "XMPP_STATUS": EIN if xmpp_domain else AUS,
        "XMPP_DOMAIN": xmpp_domain,
        "XMPP_ADRESSE": xmpp_adresse,
        "BENUTZERNAME": benutzername,
    }
    werte.update(namen)
    return werte


# ── DB-Teil ───────────────────────────────────────────────────────────────────

def werte_fuer(request):
    """Ein Aufrufbares, das die Werte für diesen Leser einmal berechnet."""
    gemerkt = {}

    def _werte():
        if not gemerkt:
            gemerkt.update(_lesen(request))
        return gemerkt

    return _werte


def _lesen(request):
    from django.urls import reverse

    from .app_settings import (
        get_base_url, get_config, get_config_bool, get_vereinsname,
        get_vereinsname_kurz, get_vereinsname_lang, is_ejabberd_configured,
    )
    from .caldav.daten import sammlung_name
    from .carddav.daten import adressbuch_name
    from .ejabberd import localpart_from_username

    basis = get_base_url() or request.build_absolute_uri("/").rstrip("/")
    secret = get_config("ICAL_SECRET")
    nutzer = getattr(request, "user", None)
    benutzername = getattr(nutzer, "username", "") or ""
    xmpp_domain = get_config("EJABBERD_HOST", "") if is_ejabberd_configured() else ""
    xmpp_adresse = getattr(nutzer, "xmpp", "") or ""
    if not xmpp_adresse and xmpp_domain and benutzername:
        xmpp_adresse = f"{localpart_from_username(benutzername)}@{xmpp_domain}"
    return werte_berechnen(
        basis=basis,
        ical_pfad=reverse("calendar_ics", args=[secret]) if secret else "",
        xmpp_domain=xmpp_domain,
        xmpp_adresse=xmpp_adresse,
        benutzername=benutzername,
        caldav_aktiv=get_config_bool("CALDAV_AKTIV", False),
        carddav_aktiv=get_config_bool("CARDDAV_AKTIV", False),
        namen={
            "KALENDER_NAME": sammlung_name("termine"),
            "GEBURTSTAGE_NAME": sammlung_name("geburtstage"),
            "ADRESSBUCH_NAME": adressbuch_name(),
            "VEREINSNAME": get_vereinsname(),
            "VEREINSNAME_LANG": get_vereinsname_lang(),
            "VEREINSNAME_KURZ": get_vereinsname_kurz(),
        },
    )
