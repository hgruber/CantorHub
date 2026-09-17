"""Email backend that reads connection settings from the database at send time.

Django instantiates the backend class each time get_connection() is called,
so reading from the DB here is safe and gives live-updateable email config.
When EMAIL_HOST is not configured, emails are written to the log and dropped.
"""
import logging

from django.core.mail.backends.smtp import EmailBackend as SmtpBackend

logger = logging.getLogger(__name__)


class DbEmailBackend(SmtpBackend):
    def __init__(self, **kwargs):
        from intern.app_settings import get_config, get_config_bool, get_config_int

        self._host_configured = bool(get_config("EMAIL_HOST", ""))
        host = get_config("EMAIL_HOST", "")
        port = get_config_int("EMAIL_PORT", 25)
        use_tls = get_config_bool("EMAIL_USE_TLS")
        use_ssl = get_config_bool("EMAIL_USE_SSL")
        username = get_config("EMAIL_HOST_USER") or None
        password = get_config("EMAIL_HOST_PASSWORD") or None

        # Django's send_mail() forwards username/password as kwargs to get_connection()
        # which passes them here — discard them so our DB values take precedence.
        kwargs.pop("username", None)
        kwargs.pop("password", None)

        super().__init__(
            host=host,
            port=port,
            username=username,
            password=password,
            use_tls=use_tls,
            use_ssl=use_ssl,
            **kwargs,
        )

    def open(self):
        # Ohne Host gibt es nichts zu verbinden — send_messages() unten schreibt dann
        # nur ins Log. Wichtig fuer den Serienversand, der die Verbindung vorab oeffnet.
        if not self._host_configured:
            return False
        return super().open()

    def send_messages(self, email_messages):
        if not self._host_configured:
            for msg in email_messages:
                logger.info(
                    "EMAIL_HOST not configured — email suppressed. "
                    "To: %s | Subject: %s | Body: %s",
                    ", ".join(msg.to),
                    msg.subject,
                    msg.body,
                )
            return len(email_messages)
        return super().send_messages(email_messages)
