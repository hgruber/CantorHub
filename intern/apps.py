import threading

from django.apps import AppConfig
from django.db.models.signals import post_migrate, post_save, pre_migrate

# Thread-local for tracking migration status
_migrating = threading.local()


_CONFIG_DEFAULTS = [
    # key, default value, description
    ("EJABBERD_ENABLED",     "0",                              "XMPP-Integration aktiv (1/0)"),
    ("EJABBERD_API_URL",     "http://127.0.0.1:5280",          "ejabberd REST API URL"),
    ("EJABBERD_HOST",        "",                               "ejabberd XMPP-Domain"),
    ("EJABBERD_MUC_SERVICE", "",                               "ejabberd MUC-Service-Domain"),
    ("EJABBERD_BOT_JID",     "",                               "JID des Forum-Bots"),
    ("EJABBERD_BOT_PASSWORD","",                               "Passwort des Forum-Bots"),
    ("EJABBERD_BOT_PORT",    "5222",                           "XMPP-Port des Forum-Bots"),
    ("ICAL_SECRET",          "",                               "Geheimes Token für iCal-Feed-URL"),
    ("EMAIL_HOST",           "",                               "SMTP-Server (leer = kein E-Mail-Versand)"),
    ("EMAIL_PORT",           "25",                             "SMTP-Port"),
    ("EMAIL_HOST_USER",      "",                               "SMTP-Benutzername"),
    ("EMAIL_HOST_PASSWORD",  "",                               "SMTP-Passwort"),
    ("EMAIL_USE_TLS",        "0",                              "SMTP STARTTLS verwenden (1/0)"),
    ("EMAIL_USE_SSL",        "0",                              "SMTP SSL verwenden (1/0)"),
    ("DEFAULT_FROM_EMAIL",   "webmaster@example.org",      "Absenderadresse für E-Mails"),
    ("UPLOAD_MAX_MB",        "50",                             "Maximale Upload-Größe in MB"),
    ("MAP_CENTER_ID",        "1",                              "ID des Orts, der als Karten-Mittelpunkt dient"),
    ("MAP_DEFAULT_ZOOM",     "12",                             "Standard-Zoomstufe der Gesamtkarte"),
    ("PWRESET_MAX_PER_HOUR", "5",                              "Maximale Passwort-Reset-Anfragen pro IP und Stunde"),
    ("NOTIFY_POLL_MS",       "10000",                          "Abfrageintervall für Benachrichtigungen (ms)"),
    ("NOTIFY_DISMISS_MS",    "6000",                           "Anzeigedauer einer Benachrichtigung (ms)"),
]


def _seed_config(sender, **kwargs):
    import secrets as _secrets
    from intern.models import Konfiguration

    for key, value, description in _CONFIG_DEFAULTS:
        Konfiguration.objects.get_or_create(
            key=key,
            defaults={"value": value, "description": description},
        )

    obj = Konfiguration.objects.get(key="ICAL_SECRET")
    if not obj.value:
        obj.value = _secrets.token_urlsafe(6)  # 8 URL-safe chars
        obj.save(update_fields=["value"])


class InternConfig(AppConfig):
    name = "intern"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        def _start_migration(sender, **kwargs):
            _migrating.active = True

        def _end_migration(sender, **kwargs):
            _migrating.active = False

        pre_migrate.connect(_start_migration, dispatch_uid="intern_start_migration")
        post_migrate.connect(_end_migration, dispatch_uid="intern_end_migration")
        post_migrate.connect(_seed_config, sender=self, dispatch_uid="intern_seed_config")

        from . import signals  # noqa: F401
