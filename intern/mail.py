"""Branded HTML email helper.

Sends a `multipart/alternative` email whose HTML part embeds the Just-Gospel
logo via ``cid:logo`` (referenced as ``<img src="cid:logo">`` in templates) and
carries a plain-text fallback. The sender address is resolved at send time via
``get_from_email()``. Never raises — failures are logged.
"""

import logging
from email import encoders
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from django.contrib.staticfiles import finders
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from intern.app_settings import get_config, get_from_email, get_vereinsname, get_vereinsname_lang, get_vereinsname_kurz, is_email_configured

logger = logging.getLogger(__name__)

_LOGO_STATIC = "intern/brand/icon-192.png"


def send_branded_mail(subject, to, template, context, text_body=None, attachments=None):
    """Render ``template`` to HTML and send it as a branded email.

    ``to`` may be a single address or an iterable of addresses (all placed in
    the To header). ``text_body`` is the plain-text fallback; a generic notice
    is used when omitted. ``attachments`` is an optional list of
    ``(filename, bytes, content_type)`` tuples added as file attachments.
    """
    recipients = [to] if isinstance(to, str) else [a for a in to if a]
    if not recipients:
        return

    html_message = render_to_string(template, {
        "vereinsname":      get_vereinsname(),
        "vereinsname_lang": get_vereinsname_lang(),
        "vereinsname_kurz": get_vereinsname_kurz(),
        "text_body":        text_body,
        **context,
    })
    plain = text_body or (
        "Bitte öffne diese Nachricht in einem HTML-fähigen E-Mail-Programm."
    )

    related = MIMEMultipart("related")
    related.attach(MIMEText(html_message, "html", "utf-8"))
    logo_path = finders.find(_LOGO_STATIC)
    if logo_path:
        with open(logo_path, "rb") as f:
            logo_img = MIMEImage(f.read())
        logo_img.add_header("Content-ID", "<logo>")
        logo_img.add_header("Content-Disposition", "inline", filename="logo.png")
        related.attach(logo_img)

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(plain, "plain", "utf-8"))
    alternative.attach(related)

    if attachments:
        mime = MIMEMultipart("mixed")
        mime.attach(alternative)
        for fname, data, ctype in attachments:
            main, sub = ctype.split("/", 1)
            part = MIMEBase(main, sub)
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=fname)
            mime.attach(part)
    else:
        mime = alternative

    mime["Subject"] = subject
    mime["From"] = get_from_email()
    mime["To"] = ", ".join(recipients)
    mime["Date"] = formatdate()
    mime["Message-ID"] = make_msgid()

    class _Msg(EmailMessage):
        def message(self, **_):
            return mime

    try:
        _Msg(subject, "", get_from_email(), recipients).send()
    except Exception:
        logger.exception("Failed to send mail '%s' to %s", subject, recipients)
        return

    if not is_email_configured():
        logger.warning(
            "EMAIL_HOST is not set in Konfiguration — email was written to console, not sent."
        )
    logger.info("Sent mail '%s' to %s", subject, recipients)


class _SafeFormatDict(dict):
    """Lässt unbekannte {Platzhalter} unverändert statt KeyError zu werfen."""
    def __missing__(self, key):
        return f"{{{key}}}"


def build_mail_placeholders(user, **extra):
    """Standardplatzhalter-Dict für alle MAIL_*-Konfigurationstexte.

    Enthält: {vorname}, {nachname}, {email}, {xmpp}, {user}, {username},
    {stimme} (ausgeschrieben), {vereinsname} — plus alle extra-Schlüssel
    (z.B. {link}).
    """
    from intern.models import User  # lazy: vermeidet zirkulären Import
    stimme_display = dict(User.STIMMEN).get(user.stimme, "") if user.stimme else ""
    return _SafeFormatDict({
        "vorname":     user.first_name or user.username,
        "nachname":    user.last_name or "",
        "email":       user.email or "",
        "xmpp":        user.xmpp or "",
        "user":        user.username,
        "username":    user.username,   # Rückwärtskompatibilität zu MAIL_ANTRAG
        "stimme":      stimme_display,
        "vereinsname": get_vereinsname(),
        **extra,
    })


def format_config_mail(key, user, **extra):
    """Liest einen MAIL_*-Konfigurationsschlüssel und füllt Platzhalter ein.

    Gibt None zurück wenn der Schlüssel leer oder nicht gesetzt ist.
    """
    raw = get_config(key)
    return raw.format_map(build_mail_placeholders(user, **extra)) if raw else None


def format_config_text(key, **kwargs):
    """Wie format_config_mail, aber ohne User-Objekt (für Mails ohne eingeloggten Empfänger).

    Verfügbare Platzhalter: {vereinsname}, {vereinsname_lang} — plus alle kwargs.
    Gibt None zurück wenn der Schlüssel leer oder nicht gesetzt ist.
    """
    raw = get_config(key)
    return raw.format_map(_SafeFormatDict({
        "vereinsname":      get_vereinsname(),
        "vereinsname_lang": get_vereinsname_lang(),
        **kwargs,
    })) if raw else None
