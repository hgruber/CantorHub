"""Vorschau der ``MAIL_*``-Texte aus der Konfiguration.

Die Konfigurationsseite öffnet bei jedem Mailtext ein überlagerndes Fenster mit
dieser Vorschau. Gezeigt wird die gespeicherte Fassung im echten Mail-Rahmen:
dasselbe Template und derselbe Kontextaufbau wie beim Versand
(``mail.render_branded_mail``), nur mit Beispielwerten für die Platzhalter und
ohne SMTP. Das Logo steht im Rahmen als ``cid:logo`` und wird für die Vorschau
als Data-URI eingebettet.

Die Registrierung ist bewusst eine Tabelle: nur ein hier eingetragener Schlüssel
bekommt den Vorschau-Link, und die Beispielwerte stehen neben dem Text, den sie
füllen.
"""

import base64
from dataclasses import dataclass, field
from typing import Mapping

from .app_settings import (
    get_config_bool, get_from_email, get_vereinsname, get_vereinsname_lang,
)
from .mail import logo_pfad, render_branded_mail, render_config_mail

# Alle Beispiel-Links zeigen auf "#". Ein erfundener Host wie
# portal.example.org endet im Browser als „Server nicht gefunden“; die
# Vorschau soll das Aussehen zeigen, nicht navigieren.
ZIEL = "#"


class BeispielMitglied:
    """Die Felder, die ``build_mail_placeholders`` von einem User liest."""

    first_name = "Anna"
    last_name = "Beispiel"
    email = "anna.beispiel@example.org"
    xmpp = "anna.beispiel@chat.example.org"
    username = "anna.beispiel"
    stimme = "S"


BEISPIEL_RUNDMAIL_TEXT = (
    "Am Samstag singen wir um 18 Uhr in der Stadtkirche.\n\n"
    "'''Bitte seid schon um 17 Uhr da.'''\n\n"
    "* Notenmappe\n"
    "* Wasserflasche"
)


@dataclass(frozen=True)
class Vorschau:
    """Wie ein Mailtext für die Vorschau zusammengesetzt wird.

    ``text_key`` leer = der Registrierungsschlüssel selbst; ``None`` = kein
    Text im Body (so zeigt ``MAIL_FOOTER`` nur den Rahmen mit Fußzeile).
    """

    template: str = "emails/generic.html"
    betreff: str = ""
    empfaenger: str = "anna.beispiel@example.org"
    link: str = ""
    mit_benutzer: bool = True
    extra_keys: tuple[str, ...] = ()
    platzhalter: Mapping[str, str] = field(default_factory=dict)
    kontext: Mapping[str, object] = field(default_factory=dict)
    text_key: str | None = ""


def _mailingliste(betreff="", **platzhalter):
    gemeinsam = {
        "abmelden": ZIEL,
        "name": "Anna Beispiel",
        "name_anrede": " Anna",
        "email": "anna.beispiel@example.org",
    }
    gemeinsam.update(platzhalter)
    return Vorschau(
        template="emails/mailingliste.html",
        betreff=betreff,
        empfaenger="anna.beispiel@example.org",
        link=gemeinsam.pop("link", ZIEL),
        mit_benutzer=False,
        platzhalter=gemeinsam,
        kontext={"abmelde_url": ZIEL},
    )


VORSCHAU: dict[str, Vorschau] = {
    "MAIL_EINLADUNG": Vorschau(
        betreff="Einladung zu {vereinsname_lang}",
        link=ZIEL,
        mit_benutzer=False,
    ),
    "MAIL_ANTRAG": Vorschau(betreff="Dein Mitgliedsantrag bei {vereinsname}"),
    "MAIL_ANTRAG_ADMIN": Vorschau(
        betreff="Neuer Mitgliedsantrag",
        empfaenger="vorstand@example.org",
        link=ZIEL,
    ),
    "MAIL_ANTRAG_ADMIN_MINDERJAEHRIG": Vorschau(
        betreff="Neuer Mitgliedsantrag",
        empfaenger="vorstand@example.org",
        link=ZIEL,
        text_key="MAIL_ANTRAG_ADMIN",
        extra_keys=("MAIL_ANTRAG_ADMIN_MINDERJAEHRIG",),
    ),
    "MAIL_ANTRAG_ADMIN_FOERDER": Vorschau(
        betreff="Neuer Mitgliedsantrag",
        empfaenger="vorstand@example.org",
        link=ZIEL,
        text_key="MAIL_ANTRAG_ADMIN",
        extra_keys=("MAIL_ANTRAG_ADMIN_FOERDER",),
    ),
    "MAIL_WILLKOMMEN": Vorschau(
        betreff="Willkommen bei {vereinsname}",
        link=ZIEL,
        kontext={"mail_title": "Willkommen bei {vereinsname}"},
    ),
    "MAIL_REAKTIVIERT": Vorschau(
        betreff="Dein Konto bei {vereinsname} wurde wieder aktiviert",
        link=ZIEL,
        kontext={"mail_title": "Dein Konto bei {vereinsname} wurde wieder aktiviert"},
    ),
    "MAIL_BESTAETIGUNG": Vorschau(
        betreff="Bitte bestätige Deine Mitgliedsdaten",
        link=ZIEL,
    ),
    "MAIL_BESTAETIGUNG_BESTAETIGT": Vorschau(
        betreff="Deine Datenbestätigung – {vereinsname}",
    ),
    "MAIL_NEUES_PASSWORT": Vorschau(
        betreff="Passwort zurücksetzen",
        link=ZIEL,
        kontext={"mail_title": "Passwort zurücksetzen"},
    ),
    "MAIL_RUNDMAIL": Vorschau(
        template="emails/mitglied_benachrichtigung.html",
        betreff="Probentermin am Samstag",
        platzhalter={"text": BEISPIEL_RUNDMAIL_TEXT},
    ),
    "MAIL_FORUM_WICHTIG": Vorschau(
        template="emails/forum_wichtig.html",
        betreff="Mitteilung von Anna Beispiel",
        link=ZIEL,
        mit_benutzer=False,
        platzhalter={"absender": "Anna Beispiel", "forum": "Vorstand"},
        kontext={
            "nachricht": "Könnt Ihr am Samstag schon um 17 Uhr da sein? "
                         "Die Bühne wird früher aufgebaut.",
            "absender_name": "Anna Beispiel",
            "forum_thema": "Vorstand",
            "datum": "05.11.2026 18:42",
        },
    ),
    "MAIL_FOOTER": Vorschau(
        betreff="Vorschau der Fußzeile",
        text_key=None,
    ),
    "MAIL_MAILINGLISTE_OPTIN": _mailingliste(
        betreff="Bitte bestätige Deine Anmeldung",
        link=ZIEL,
    ),
    "MAIL_MAILINGLISTE_WILLKOMMEN": _mailingliste(
        betreff="Willkommen auf unserer Auftritts-Liste",
    ),
    "MAIL_MAILINGLISTE_BEREITS_ANGEMELDET": _mailingliste(
        betreff="Du stehst bereits auf unserer Auftritts-Liste",
    ),
    "MAIL_MAILINGLISTE_ERINNERUNG": _mailingliste(
        betreff="Information: {titel} am {datum}",
        titel="Sommerkonzert",
        datum="14.06.2027",
        wochentag="Montag",
        uhrzeit="19:30",
        uhrzeit_text=" um 19:30 Uhr",
        ort="Stadtkirche",
        ort_adresse="Marktplatz 1 12345 Musterstadt",
        extern="Eintritt frei, Spenden willkommen.",
        wochen="4",
        wochen_text="vier Wochen",
    ),
}


def hat_vorschau(key: str) -> bool:
    return key in VORSCHAU


def _betreff(spec: Vorschau) -> str:
    werte = {
        "vereinsname": get_vereinsname(),
        "vereinsname_lang": get_vereinsname_lang(),
        "titel": spec.platzhalter.get("titel", ""),
        "datum": spec.platzhalter.get("datum", ""),
    }
    try:
        return spec.betreff.format(**werte)
    except (KeyError, IndexError):
        return spec.betreff


def _logo_einbetten(html: str) -> str:
    """``src="cid:logo"`` durch das eingebettete Logo ersetzen.

    In einer echten Mail hängt das Bild als ``Content-ID: <logo>`` am MIME-Teil;
    die Vorschau steht im Browser und braucht deshalb eine Data-URI.
    """
    pfad = logo_pfad()
    if pfad is None:
        return html
    daten = base64.b64encode(pfad.read_bytes()).decode("ascii")
    return html.replace('src="cid:logo"', f'src="data:image/png;base64,{daten}"')


def vorschau_kopf(key: str):
    """Kopfzeilen der Vorschau (Betreff, Absender, Empfänger) oder ``None``.

    Das Vorschaufenster braucht nur sie; der Mail-Rahmen selbst wird über eine
    eigene Adresse geladen (``mailvorschau_rahmen``), damit Firefox ihn nicht
    wegen ``X-Frame-Options: DENY`` blockt.
    """
    spec = VORSCHAU.get(key)
    if spec is None:
        return None
    return {
        "key": key,
        "betreff": _betreff(spec),
        "von": get_from_email(),
        "an": spec.empfaenger,
    }


def vorschau(key: str):
    """Die fertige Vorschau zu ``key`` oder ``None``, wenn er keine hat."""
    kopf = vorschau_kopf(key)
    if kopf is None:
        return None
    spec = VORSCHAU[key]

    betreff = kopf["betreff"]
    if spec.text_key is None:
        body_html = ""
    else:
        body_html, _plain = render_config_mail(
            spec.text_key or key,
            user=BeispielMitglied() if spec.mit_benutzer else None,
            link=spec.link,
            extra_keys=spec.extra_keys,
            **spec.platzhalter,
        )

    kontext = {"mail_title": betreff, "body_html": body_html, **spec.kontext}
    if key == "MAIL_RUNDMAIL":
        kontext.update({
            "signature_group_name": "Vorstand",
            "signature_members": (
                ["Anna Beispiel", "Bruno Beispiel"]
                if get_config_bool("MAIL_SIGNATUR_MITGLIEDER_ANZEIGEN") else []
            ),
            "absender_name": "Clara Vorstand",
        })
    html, _plain_mit_footer = render_branded_mail(spec.template, kontext)

    return {**kopf, "html": _logo_einbetten(html)}
