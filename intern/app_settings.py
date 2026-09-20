"""Runtime configuration from the database (intern.Konfiguration).

Use these helpers instead of os.environ / django.conf.settings for any setting
that should be changeable without redeploying.  The DB must be available when
these are called — they are intentionally not called at import/settings-load time.

Environment variables take priority over DB values so that container deployments
can configure the app via -e flags without needing an initial.sh or admin access.
"""

import os
import threading
from contextlib import contextmanager

# Zwischenspeicher für die Dauer einer Anfrage.
#
# Jede Seite liest ein knappes Dutzend Schlüssel — allein der Kontextprozessor in
# config/context_processors.py neun —, und jeder einzelne war ein eigener SELECT.
# Die Tabelle hat unter hundert Zeilen, ein Komplettabzug ist also billiger als
# schon der zweite Roundtrip.
#
# Der Zwischenspeicher lebt ausschließlich innerhalb einer Anfrage: ``request_started``
# legt ihn an, ``request_finished`` wirft ihn weg (verbunden in signals.py). Außerhalb
# einer Anfrage greift er bewusst nicht — zwei Management-Kommandos laufen als
# Dauerschleife (``ejabberd_bot``, ``send_auftritt_erinnerungen``), die sähen sonst bis
# zum Prozessende die Konfiguration ihres Startzeitpunkts. Dort bleibt es beim
# Einzelquery pro Schlüssel, so wie bisher.
_lokal = threading.local()

# Unterscheidet „Anfrage läuft, noch nichts gelesen" von „keine Anfrage" (None).
_UNGELESEN = object()


def cache_anlegen(**kwargs):
    """``request_started``: ab hier wird zwischengespeichert, gelesen wird beim ersten Zugriff."""
    _lokal.werte = _UNGELESEN


def cache_verwerfen(**kwargs):
    """``request_finished``: der Thread bedient als nächstes eine fremde Anfrage."""
    _lokal.werte = None


def cache_leeren(**kwargs):
    """Erzwingt ein Neulesen, ohne den Zwischenspeicher abzuschalten.

    Hängt an ``post_save``/``post_delete`` von ``Konfiguration``: wer innerhalb
    einer Anfrage schreibt und danach liest, muss seinen eigenen Wert sehen.
    """
    if getattr(_lokal, "werte", None) is not None:
        _lokal.werte = _UNGELESEN


@contextmanager
def konfiguration_gepuffert():
    """Öffnet den Zwischenspeicher für einen abgegrenzten Block außerhalb einer Anfrage.

    Für den Massenversand: ``send_branded_mail`` liest pro Empfänger sechzehn Werte
    (Vereinsname dreifach, Brand-Farbe, Footer, Absender), die sich während eines
    Durchlaufs nicht ändern — ohne diesen Block sind das sechzehn SELECTs mal Anzahl
    der Empfänger.

    Gehört um **einen Durchlauf**, nie um die Dauerschleife eines Kommandos: sonst
    gilt bis zum Prozessende die Konfiguration des Starts, und genau das soll der
    Zwischenspeicher außerhalb von Anfragen ja vermeiden.

    Läuft verschachtelt sauber: innerhalb einer Anfrage (oder eines äußeren Blocks)
    lässt er den vorhandenen Zwischenspeicher unangetastet, statt ihn am Ende
    wegzuwerfen und den Rest der Anfrage wieder auf Einzelabfragen zu werfen.
    """
    schon_offen = getattr(_lokal, "werte", None) is not None
    if not schon_offen:
        cache_anlegen()
    try:
        yield
    finally:
        if not schon_offen:
            cache_verwerfen()


def _werte():
    """Alle Konfigurationszeilen als ``dict``, oder ``None`` außerhalb einer Anfrage."""
    werte = getattr(_lokal, "werte", None)
    if werte is None:
        return None
    if werte is _UNGELESEN:
        try:
            from intern.models import Konfiguration
            werte = dict(Konfiguration.objects.values_list("key", "value"))
        except Exception:
            # Gleiche Haltung wie in get_config: ohne greifbare Datenbank gilt der
            # Vorgabewert. Auch das leere Ergebnis wird gemerkt, sonst liefe jeder
            # einzelne Schlüssel erneut in denselben Fehler.
            werte = {}
        _lokal.werte = werte
    return werte


def get_config(key, default=None):
    env_val = os.environ.get(key)
    if env_val is not None:
        return env_val
    werte = _werte()
    if werte is not None:
        return werte.get(key, default)
    try:
        from intern.models import Konfiguration
        return Konfiguration.objects.get(key=key).value
    except Exception:
        return default


def is_ejabberd_configured():
    """Return True when ejabberd credentials are present (env or DB).

    Replaces the old EJABBERD_ENABLED flag — if EJABBERD_HOST and
    EJABBERD_BOT_JID are set, the integration is active.
    """
    return bool(get_config("EJABBERD_HOST")) and bool(get_config("EJABBERD_BOT_JID"))


def get_config_bool(key, default=False):
    val = get_config(key)
    if val is None:
        return default
    return val == "1"


def get_config_int(key, default=0):
    val = get_config(key)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_zeitzone():
    """IANA-Zeitzonenname des Portals, als Zeichenkette.

    Liest ``ZEITZONE`` (Env hat Vorrang, siehe ``get_config``), prüft gegen
    ``zoneinfo.available_timezones()`` und fällt bei fehlendem oder ungültigem
    Wert auf ``settings.TIME_ZONE`` zurück. So kann CalDAV ohne erneutes Deploy
    auf eine andere Zone umgestellt werden, ohne dass ein Tippfehler den
    Kalender-Export zum Absturz bringt.
    """
    from django.conf import settings
    from zoneinfo import available_timezones

    roh = get_config("ZEITZONE")
    if roh and roh in available_timezones():
        return roh
    return settings.TIME_ZONE


def get_sprache():
    """Sprachkennung des Portals (``de-de``), als Zeichenkette.

    Liest ``SPRACHE`` (Env hat Vorrang, siehe ``get_config``) und prüft gegen
    Djangos eigene Sprachliste; bei fehlendem oder unbekanntem Wert bleibt es
    bei ``settings.LANGUAGE_CODE``. Wie bei ``get_zeitzone`` soll ein Tippfehler
    in der Konfiguration nichts zum Absturz bringen.

    Die Portaltexte sind fest deutsch. Der Wert wirkt auf Djangos eigene Texte
    und auf die Datums- und Zahlenformate.
    """
    from django.conf import global_settings, settings

    roh = get_config("SPRACHE")
    if not roh:
        return settings.LANGUAGE_CODE
    bekannt = {code.lower() for code, _ in global_settings.LANGUAGES}
    if roh.lower() in bekannt:
        return roh.lower()
    # "de-de" ist kein eigener Eintrag in LANGUAGES, "de" schon — Django fällt
    # intern ohnehin auf den Hauptsprachcode zurück, also hier genauso.
    if roh.lower().split("-")[0] in bekannt:
        return roh.lower()
    return settings.LANGUAGE_CODE


def get_config_list(key, default=""):
    """Kommaseparierten Konfigurationswert als Liste von Strings.

    Leere Einträge und umgebende Leerzeichen fallen weg.  Die Umwandlung in
    Zahlen gehört bewusst nicht hierher — sie ist je nach Schlüssel anders
    (siehe parse_wochen in intern/mailingliste.py).
    """
    raw = get_config(key)
    if raw is None:
        raw = default
    return [teil.strip() for teil in str(raw).split(",") if teil.strip()]


def is_email_configured():
    return bool(get_config("EMAIL_HOST"))


def get_from_email():
    """Sender address for outgoing mail.

    Prefers the DB-configured DEFAULT_FROM_EMAIL, falling back to the
    settings value so mail still has a sender before the DB is seeded.
    """
    from django.conf import settings
    return get_config("DEFAULT_FROM_EMAIL") or settings.DEFAULT_FROM_EMAIL


def get_vereinsname():
    return get_config("VEREINSNAME", "Join us singing the Gospel e.V.")


def get_vereinsname_lang():
    return get_config("VEREINSNAME_LANG", "Just Gospel! Frankfurt")


def get_vereinsname_kurz():
    return get_config("VEREINSNAME_KURZ", "Just Gospel")


def get_brand_farbe():
    return get_config("BRAND_FARBE", "#c14468")


def get_base_url(override=None, fallback=""):
    """Basis-URL des Portals (Schema + Host), garantiert ohne Schrägstrich am Ende.

    Für jede URL, die außerhalb eines Requests gebaut wird — Mails, Management-
    Kommandos, PDFs. Wo ein Request vorliegt, ist `request.build_absolute_uri()`
    die bessere Quelle.

    `fallback` bleibt bewusst leer: für den Mailversand ist eine fehlende
    VEREINS_URL eine Abbruchbedingung (ein relativer Abmelde-Link wäre tot), und
    ein stillschweigendes http://localhost würde genau das verschleiern. Nur die
    interaktiven Kommandos, die eine URL bloß ausgeben, setzen einen.
    """
    return (override or get_config("VEREINS_URL", "") or fallback).strip().rstrip("/")


def get_document_url(config_key):
    """Gibt die HMAC-Token-URL für ein öffentliches Dokument zurück, oder '#' wenn nicht konfiguriert."""
    from filer.models import File as FilerFile
    from intern.views.media import file_token
    file_id = get_config_int(config_key)
    if not file_id:
        return "#"
    try:
        f = FilerFile.objects.get(pk=file_id)
        return f"/intern/datei/{file_id}/{file_token(file_id)}/{f.original_filename}"
    except FilerFile.DoesNotExist:
        return "#"


def get_map_center():
    """Return (lat, lng) from the Ort configured as MAP_CENTER_ID.

    Fällt auf MAP_CENTER_LAT / MAP_CENTER_LNG zurück, wenn der Ort keine
    Koordinaten hat oder nicht existiert — früher hartkodiert Frankfurt.
    """
    from intern.models import Ort
    ort_id = get_config_int("MAP_CENTER_ID", 1)
    try:
        ort = Ort.objects.get(pk=ort_id)
        if ort.breite is not None and ort.laenge is not None:
            return (ort.breite, ort.laenge)
    except Exception:
        pass
    lat = float(get_config("MAP_CENTER_LAT", "50.1109"))
    lng = float(get_config("MAP_CENTER_LNG", "8.6821"))
    return (lat, lng)
