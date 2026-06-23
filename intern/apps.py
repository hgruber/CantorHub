import threading

from django.apps import AppConfig
from django.db.models.signals import post_migrate, post_save, pre_migrate

# Thread-local for tracking migration status
_migrating = threading.local()


_CONFIG_DEFAULTS = [
    # key, default value, description
    ("EJABBERD_API_URL", "http://127.0.0.1:5280", "ejabberd REST API URL"),
    ("EJABBERD_HOST", "", "ejabberd XMPP-Domain"),
    ("EJABBERD_MUC_SERVICE", "", "ejabberd MUC-Service-Domain"),
    ("EJABBERD_BOT_JID", "", "JID des Forum-Bots"),
    ("EJABBERD_BOT_PASSWORD", "", "Passwort des Forum-Bots"),
    ("EJABBERD_BOT_PORT", "5222", "XMPP-Port des Forum-Bots"),
    ("ICAL_SECRET", "", "Geheimes Token für iCal-Feed-URL"),
    ("EMAIL_HOST", "", "SMTP-Server (leer = kein E-Mail-Versand)"),
    ("EMAIL_PORT", "25", "SMTP-Port"),
    ("EMAIL_HOST_USER", "", "SMTP-Benutzername"),
    ("EMAIL_HOST_PASSWORD", "", "SMTP-Passwort"),
    ("EMAIL_USE_TLS", "0", "SMTP STARTTLS verwenden (1/0)"),
    ("EMAIL_USE_SSL", "0", "SMTP SSL verwenden (1/0)"),
    ("DEFAULT_FROM_EMAIL", "webmaster@example.org", "Absenderadresse für E-Mails"),
    ("UPLOAD_MAX_MB", "50", "Maximale Upload-Größe in MB"),
    ("MAP_CENTER_ID", "1", "ID des Orts, der als Karten-Mittelpunkt dient"),
    ("MAP_DEFAULT_ZOOM", "12", "Standard-Zoomstufe der Gesamtkarte"),
    ("PWRESET_MAX_PER_HOUR", "5", "Maximale Passwort-Reset-Anfragen pro IP und Stunde"),
    ("NOTIFY_POLL_MS", "10000", "Abfrageintervall für Benachrichtigungen (ms)"),
    ("NOTIFY_DISMISS_MS", "6000", "Anzeigedauer einer Benachrichtigung (ms)"),
    ("VEREINSNAME", "Join us singing the Gospel", "Name des Chors"),
    (
        "VEREINSNAME_LANG",
        "Just Gospel! Frankfurt",
        "Langer Vereinsname mit Ort (für E-Mail-Header, Seitentitel)",
    ),
    ("VEREINSNAME_KURZ", "Just Gospel", "Kurzer Vereinsname (für Sidebar, Alt-Texte)"),
    (
        "VEREINSADRESSE",
        "",
        "Ladungsfähige Kontaktanschrift des Vereins (Datenschutzerklärung §1, "
        "mehrzeilig erlaubt; leer → es werden nur die Vorstandsnamen genannt)",
    ),
    (
        "MAIL_ANTRAG",
        "Hallo {vorname},\n\n"
        "vielen Dank für Deinen Mitgliedsantrag. Wir haben ihn erhalten.\n"
        "Du erhältst eine weitere Nachricht, sobald dieser geprüft ist.\n\n"
        "Dein gewünschter Benutzername: {username}",
        "Bestätigungsmail an Antragsteller (Platzhalter: {vorname}, {nachname}, {email}, {xmpp}, {user}, {username}, {stimme}, {vereinsname})",
    ),
    (
        "MAIL_ANTRAG_ADMIN",
        "Es liegt ein neuer Mitgliedsantrag vor:\n\n{vorname} {nachname} ({email})\n\nDetails: {link}",
        "Admin-Benachrichtigung bei neuem Antrag (Platzhalter: {vorname}, {nachname}, {email}, {link}, {vereinsname})",
    ),
    (
        "SATZUNG_FILE_ID",
        "",
        "Filer-Datei-ID der aktuellen Satzung (leer → kein Link in Formularen)",
    ),
    (
        "VEREINS_URL",
        "",
        "Basis-URL des Portals für Links in E-Mails (z.B. https://portal.example.com)",
    ),
    (
        "MAIL_BEI_AKTIVIERUNG",
        "1",
        "Aktivierungsmails versenden (0 = deaktiviert, z.B. während Tests)",
    ),
    (
        "MAIL_BESTAETIGUNG",
        "Liebe/r {vorname},\n\n"
        "wir bitten Dich, Deine im Mitgliederportal gespeicherten Daten zu prüfen "
        "und zu bestätigen, dass sie korrekt und aktuell sind.\n\n"
        "Gleichzeitig bitten wir Dich, unsere Datenschutzerklärung, die Satzung "
        "sowie die Beitragsordnung des Chors erneut zu bestätigen.\n\n"
        "Bitte klicke auf den folgenden Link (gültig 30 Tage):\n"
        "{link}\n\n"
        "Herzliche Grüße\n"
        "Dein Vorstand von {vereinsname}",
        "Text der Datenbestätigungs-Mail (Platzhalter: {vorname}, {nachname}, {email}, {xmpp}, {user}, {stimme}, {link}, {vereinsname})",
    ),
    (
        "MAIL_BESTAETIGUNG_BESTAETIGT",
        "Hallo {vorname},\n\nvielen Dank für Deine Bestätigung! Anbei findest Du eine Kopie als PDF.\n\n"
        "Herzliche Grüße\nDein Vorstand von {vereinsname}",
        "Quittung an Mitglied nach Datenbestätigung (Platzhalter: {vorname}, {vereinsname})",
    ),
    (
        "MAIL_EINLADUNG",
        "Hallo,\n\nDu wurdest eingeladen, Mitglied bei {vereinsname_lang} zu werden.\n"
        "Über diesen Link kannst Du Deinen Antrag ausfüllen (7 Tage gültig):\n\n{link}",
        "Einladungs-Mail (Platzhalter: {link}, {vereinsname}, {vereinsname_lang})",
    ),
    (
        "MAIL_NEUES_PASSWORT",
        "Hallo {vorname},\n\nüber diesen Link kannst Du ein neues Passwort für Deinen "
        "Benutzer '{user}' setzen:\n\n{link}\n\nWenn Du das nicht angefordert hast, kannst "
        "Du diese E-Mail ignorieren — Dein Passwort bleibt unverändert.",
        "Passwort-zurücksetzen-Mail (Platzhalter: {vorname}, {nachname}, {email}, {xmpp}, {user}, {stimme}, {link}, {vereinsname})",
    ),
    (
        "MAIL_WILLKOMMEN",
        "Liebe/r {vorname},\n\nwir freuen uns sehr, Dich als neues Mitglied bei {vereinsname} begrüßen zu dürfen!\n\n"
        "Dein Benutzerkonto ist jetzt freigeschaltet. Du kannst Dich ab sofort im Mitgliederportal anmelden.\n\n"
        "Herzliche Grüße\nDein Vorstand von {vereinsname}",
        "Willkommens-Mail bei erster Aktivierung (Platzhalter: {vorname}, {nachname}, {email}, {xmpp}, {user}, {stimme}, {link}, {vereinsname})",
    ),
    (
        "MAIL_REAKTIVIERT",
        "Liebe/r {vorname},\n\nDein Mitgliedskonto bei {vereinsname} wurde wieder aktiviert.\n\n"
        "Du kannst Dich ab sofort wieder im Mitgliederportal anmelden.\n\n"
        "Herzliche Grüße\nDein Vorstand von {vereinsname}",
        "Mail bei Reaktivierung eines Mitglieds (Platzhalter: {vorname}, {nachname}, {email}, {xmpp}, {user}, {stimme}, {link}, {vereinsname})",
    ),
]


def _seed_config(sender, **kwargs):
    import os
    import secrets as _secrets

    from intern.models import Konfiguration

    for key, value, description in _CONFIG_DEFAULTS:
        env_val = os.environ.get(key)
        if env_val is not None:
            Konfiguration.objects.update_or_create(
                key=key,
                defaults={"value": env_val, "description": description},
            )
        else:
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
        post_migrate.connect(
            _seed_config, sender=self, dispatch_uid="intern_seed_config"
        )

        from . import signals  # noqa: F401
