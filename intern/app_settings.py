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
