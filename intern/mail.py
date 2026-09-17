"""Branded HTML email helper.

Sends a `multipart/alternative` email whose HTML part embeds the Just-Gospel
logo via ``cid:logo`` (referenced as ``<img src="cid:logo">`` in templates) and
carries a plain-text fallback. The sender address is resolved at send time via
``get_from_email()``. Never raises — failures are logged.
"""

import logging
from email import encoders, policy as _email_policy
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from django.contrib.staticfiles import finders
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from intern.app_settings import get_brand_farbe, get_config, get_from_email, get_vereinsname, get_vereinsname_lang, get_vereinsname_kurz, is_email_configured

logger = logging.getLogger(__name__)

_LOGO_STATIC = "intern/brand/icon-192.png"

# Inline-Farben fuer die HTML-Mails. E-Mail-Clients koennen var() nicht
# verlaesslich, daher werden die Farben als String direkt ins Template
# geschrieben. Die Werte entsprechen den CSS-Tokens in intern.css :root
# (--bg-app, --bg-card, --t2, --t3, --border) und muessen parallel zu diesen
# gepflegt werden. Die Akzentfarbe (brand_farbe) ist einziger konfigurierbarer
# Farbwert und wird separat als ``brand_farbe`` in den Kontext gelegt.
_MAIL_FARBE = {
    "mail_farbe_bg":      "#f1f3f5",  # --bg-app
    "mail_farbe_card":    "#ffffff",  # --bg-card
    "mail_farbe_border":  "#e5e7eb",  # --border
    "mail_farbe_text":    "#374151",  # --t2
    "mail_farbe_muted":   "#6b7280",  # --t3
    "mail_farbe_onbrand": "#ffffff",  # Kontrastfarbe auf Brand-Hintergrund
}

# Zeilenenden fuer den SMTP-Transport (RFC 5321). Bewusst compat32 und nicht
# email.policy.SMTP: die Nachricht wird mit der alten MIME-API gebaut, ein
# Wechsel der Policy wuerde auch die Kopfzeilen-Kodierung veraendern.
_SMTP_POLICY = _email_policy.compat32.clone(linesep="\r\n")


def send_branded_mail(subject, to, template, context, text_body=None, attachments=None,
                      headers=None, connection=None):
    """Render ``template`` to HTML and send it as a branded email.

    ``to`` may be a single address or an iterable of addresses (all placed in
    the To header). ``text_body`` is the plain-text fallback; a generic notice
    is used when omitted. ``attachments`` is an optional list of
    ``(filename, bytes, content_type)`` tuples added as file attachments.
    ``headers`` is an optional dict of extra MIME headers (e.g. List-Unsubscribe).
    ``connection`` is an opened mail backend shared by a bulk send; without it
    every call opens (and closes) its own SMTP connection.

    Returns True when the message was handed to the mail backend, False otherwise.
    """
    recipients = [to] if isinstance(to, str) else [a for a in to if a]
    if not recipients:
        return False

    footer = render_config_mail("MAIL_FOOTER")[1].strip()
    html_message = render_to_string(template, {
        "vereinsname":      get_vereinsname(),
        "vereinsname_lang": get_vereinsname_lang(),
        "vereinsname_kurz": get_vereinsname_kurz(),
        "brand_farbe":      get_brand_farbe(),
        **_MAIL_FARBE,
        "text_body":        text_body,
        "mail_footer":      footer,
        **context,
    })
    plain = text_body or (
        "Bitte öffne diese Nachricht in einem HTML-fähigen E-Mail-Programm."
    )
    if footer:
        plain = f"{plain.rstrip()}\n\n-- \n{footer}"

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
    for name, value in (headers or {}).items():
        mime[name] = value

    class _Msg(EmailMessage):
        def message(self, policy=None, **_):
            # Django reicht hier policy=email.policy.SMTP herein. Ohne sie
            # serialisiert as_bytes() mit blossen LF-Zeilenenden — RFC 5321
            # verlangt CRLF, und strenge SMTP-Server lehnen die Nachricht dann
            # als eine einzige zu lange Zeile ab. compat32 mit CRLF statt
            # policy.SMTP, damit die Kopfzeilen-Kodierung unveraendert bleibt.
            mime.policy = _SMTP_POLICY
            return mime

    try:
        _Msg(subject, "", get_from_email(), recipients, connection=connection).send()
    except Exception:
        logger.exception("Failed to send mail '%s' to %s", subject, recipients)
        return False

    if not is_email_configured():
        logger.warning(
            "EMAIL_HOST is not set in Konfiguration — email was written to console, not sent."
        )
    logger.info("Sent mail '%s' to %s", subject, recipients)
    return True


def build_mail_placeholders(user=None, **extra):
    """Standardplatzhalter-Dict für alle MAIL_*-Konfigurationstexte.

    Immer verfügbar: {vereinsname}, {vereinsname_lang}, {vereinsname_kurz}.
    Mit ``user`` zusätzlich: {vorname}, {nachname}, {email}, {xmpp}, {user},
    {username}, {stimme} (ausgeschrieben). Dazu alle extra-Schlüssel (z.B. {link}).
    """
    values = {
        "vereinsname":      get_vereinsname(),
        "vereinsname_lang": get_vereinsname_lang(),
        "vereinsname_kurz": get_vereinsname_kurz(),
    }
    if user is not None:
        from intern.models import User  # lazy: vermeidet zirkulären Import
        stimme_display = dict(User.STIMMEN).get(user.stimme, "") if user.stimme else ""
        values.update({
            "vorname":  user.first_name or user.username,
            "nachname": user.last_name or "",
            "email":    user.email or "",
            "xmpp":     user.xmpp or "",
            "user":     user.username,
            "username": user.username,   # Rückwärtskompatibilität zu MAIL_ANTRAG
            "stimme":   stimme_display,
        })
    values.update(extra)
    return values


def render_mail_text(raw, user=None, link=None, **extra):
    """Rendert einen Mailtext (Wiki-Markup + Platzhalter) zu ``(html, plain)``.

    ``link`` ist das Ziel für ``{button:Label}`` und steht zusätzlich als
    Platzhalter ``{link}`` zur Verfügung.
    """
    from intern.mail_markup import render_mail_markup
    extra.setdefault("link", link or "")
    return render_mail_markup(raw, build_mail_placeholders(user, **extra), link=link)


def render_config_mail(key, user=None, link=None, extra_keys=(), **extra):
    """Wie ``render_mail_text``, liest den Text aber aus der Konfiguration.

    ``extra_keys`` sind weitere Konfigurationsschlüssel mit bedingten Hinweisen.
    Deren Texte landen im Platzhalter ``{hinweise}`` — enthält der Haupttext ihn
    nicht, werden sie angehängt, damit ein Hinweis nie stillschweigend verloren
    geht. Ist kein Text gesetzt, kommt ``("", "")`` zurück.
    """
    raw = (get_config(key) or "").strip()
    hinweise = "\n\n".join(
        text.strip() for text in (get_config(k) for k in extra_keys) if text and text.strip()
    )
    if "{hinweise}" in raw:
        extra.setdefault("hinweise", hinweise)
    elif hinweise:
        raw = f"{raw}\n\n{hinweise}" if raw else hinweise
    return render_mail_text(raw, user, link, **extra)


def send_config_mail(subject, to, key, user=None, link=None, extra_keys=(),
                     attachments=None, template="emails/generic.html",
                     context=None, connection=None, **extra):
    """Rendert einen MAIL_*-Konfigurationstext und verschickt ihn als Mail.

    Der gerenderte HTML-Teil kommt als ``body_html`` in den Template-Kontext,
    der Plain-Text-Teil wird zum ``text/plain``-Teil der Mail. ``connection``
    wie bei ``send_branded_mail``.
    """
    body_html, plain = render_config_mail(
        key, user=user, link=link, extra_keys=extra_keys, **extra
    )
    return send_branded_mail(
        subject,
        to,
        template,
        {"body_html": body_html, **(context or {})},
        text_body=plain,
        attachments=attachments,
        connection=connection,
    )


def versende_serie(empfaenger, senden, neu_verbinden):
    """Schickt jedem Eintrag aus ``empfaenger`` seine Mail, mit einem Wiederholversuch.

    ``senden(eintrag)`` liefert True bei Erfolg (``send_branded_mail`` wirft nie).
    Schlaegt ein Versand fehl, ist meist die gemeinsame SMTP-Verbindung weg — der
    Server hat sie nach einer Hoechstzahl an Nachrichten oder nach Leerlauf
    geschlossen. Deshalb ``neu_verbinden()`` und genau ein zweiter Versuch; erst
    danach gilt der Eintrag als fehlgeschlagen und der Rest geht trotzdem raus.

    Frei von Datenbank und SMTP, damit die Schleife testbar bleibt.
    Gibt ``(gesendet, fehlgeschlagen)`` als zwei Listen der Eintraege zurueck.
    """
    gesendet, fehlgeschlagen = [], []
    for eintrag in empfaenger:
        if senden(eintrag):
            gesendet.append(eintrag)
            continue
        neu_verbinden()
        if senden(eintrag):
            gesendet.append(eintrag)
        else:
            fehlgeschlagen.append(eintrag)
    return gesendet, fehlgeschlagen


def neu_verbinden(connection):
    """Schliesst eine (womoeglich schon tote) SMTP-Verbindung und oeffnet sie neu."""
    try:
        connection.close()
    except Exception:
        pass
    try:
        connection.open()
    except Exception:
        # Kein Abbruch: send_messages() versucht beim naechsten Senden selbst zu
        # verbinden, und scheitert das, zaehlt der Eintrag als fehlgeschlagen.
        logger.warning("SMTP-Verbindung konnte nicht neu geoeffnet werden.", exc_info=True)
