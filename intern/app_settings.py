"""Runtime configuration from the database (intern.Konfiguration).

Use these helpers instead of os.environ / django.conf.settings for any setting
that should be changeable without redeploying.  The DB must be available when
these are called — they are intentionally not called at import/settings-load time.
"""


def get_config(key, default=None):
    try:
        from intern.models import Konfiguration
        return Konfiguration.objects.get(key=key).value
    except Exception:
        return default


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


def is_email_configured():
    return bool(get_config("EMAIL_HOST"))


def get_from_email():
    """Sender address for outgoing mail.

    Prefers the DB-configured DEFAULT_FROM_EMAIL, falling back to the
    settings value so mail still has a sender before the DB is seeded.
    """
    from django.conf import settings
    return get_config("DEFAULT_FROM_EMAIL") or settings.DEFAULT_FROM_EMAIL


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
