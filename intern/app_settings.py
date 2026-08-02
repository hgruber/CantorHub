"""Runtime configuration from the database (intern.Konfiguration).

Use these helpers instead of os.environ / django.conf.settings for any setting
that should be changeable without redeploying.  The DB must be available when
these are called — they are intentionally not called at import/settings-load time.

Environment variables take priority over DB values so that container deployments
can configure the app via -e flags without needing an initial.sh or admin access.
"""

import os


def get_config(key, default=None):
    env_val = os.environ.get(key)
    if env_val is not None:
        return env_val
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
    return get_config("VEREINSNAME", "Join us singing the Gospel")


def get_vereinsname_lang():
    return get_config("VEREINSNAME_LANG", "Just Gospel! Frankfurt")


def get_vereinsname_kurz():
    return get_config("VEREINSNAME_KURZ", "Just Gospel")


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
    """Return (lat, lng) from the Ort configured as MAP_CENTER_ID."""
    from intern.models import Ort
    ort_id = get_config_int("MAP_CENTER_ID", 1)
    try:
        ort = Ort.objects.get(pk=ort_id)
        if ort.breite is not None and ort.laenge is not None:
            return (ort.breite, ort.laenge)
    except Exception:
        pass
    return (50.1109, 8.6821)
