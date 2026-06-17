"""Branded HTML email helper.

Sends a `multipart/alternative` email whose HTML part embeds the Just-Gospel
logo via ``cid:logo`` (referenced as ``<img src="cid:logo">`` in templates) and
carries a plain-text fallback. The sender address is resolved at send time via
``get_from_email()``. Never raises — failures are logged.
"""

import logging
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from django.contrib.staticfiles import finders
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from intern.app_settings import get_from_email, is_email_configured

logger = logging.getLogger(__name__)

_LOGO_STATIC = "intern/images/icon-192.png"


def send_branded_mail(subject, to, template, context, text_body=None):
    """Render ``template`` to HTML and send it as a branded email.

    ``to`` may be a single address or an iterable of addresses (all placed in
    the To header). ``text_body`` is the plain-text fallback; a generic notice
    is used when omitted.
    """
    recipients = [to] if isinstance(to, str) else [a for a in to if a]
    if not recipients:
        return

    html_message = render_to_string(template, context)
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

    mime = MIMEMultipart("alternative")
    mime["Subject"] = subject
    mime["From"] = get_from_email()
    mime["To"] = ", ".join(recipients)
    mime["Date"] = formatdate()
    mime["Message-ID"] = make_msgid()
    mime.attach(MIMEText(plain, "plain", "utf-8"))
    mime.attach(related)

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
