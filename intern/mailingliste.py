"""Domänenlogik der öffentlichen Auftritts-Mailingliste.

Hier steht alles, was weder HTTP noch Management-Command braucht: Tokens, URLs,
Fälligkeitsrechnung, Platzhalter und der Mailversand mit unverzichtbarem
Abmelde-Link.  Die zeitabhängigen Funktionen bekommen „jetzt" übergeben und
rufen selbst keine Uhr auf — nur so sind sie ohne Datenbank und ohne
Uhr-Manipulation testbar (und der Command kann ``--now`` anbieten).

``USE_TZ = False``: ``Termin.datum`` und ``timezone.now()`` sind beide naive
lokale Wanduhrzeit.  ``localtime()`` darf hier nirgends aufgerufen werden.
"""

import hashlib
import logging
from datetime import datetime, time, timedelta

from django.core.signing import BadSignature, SignatureExpired, Signer, TimestampSigner
from django.utils import timezone

from intern.app_settings import (
    get_base_url,
    get_config,
    get_config_int,
    get_config_list,
    get_from_email,
)
from intern.mail import render_config_mail, send_branded_mail

logger = logging.getLogger(__name__)

# Missbrauchsschutz, bewusst Konstanten und keine Konfigurationsschlüssel —
# das sind keine redaktionellen Parameter.
KULANZ_STUNDEN = 24      # nach einem Serverausfall keine sinnlos verspäteten Mails
OPTIN_COOLDOWN_MIN = 10  # Bremse gegen Mail-Bombing auf eine fremde Adresse

_optin_signer = TimestampSigner(salt="intern.mailingliste_optin")
_abmelde_signer = Signer(salt="intern.mailingliste_abmelden")

_WOCHENTAGE = (
    "Montag", "Dienstag", "Mittwoch", "Donnerstag",
    "Freitag", "Samstag", "Sonntag",
)

# Ausgeschriebene Zahlwörter für „in {wochen_text}" — darüber hinaus Ziffern.
_ZAHLWORT = {
    1: "einer", 2: "zwei", 3: "drei", 4: "vier", 5: "fünf", 6: "sechs",
    7: "sieben", 8: "acht", 9: "neun", 10: "zehn", 11: "elf", 12: "zwölf",
}


# ---------------------------------------------------------------------------
# Tokens und URLs
# ---------------------------------------------------------------------------

def optin_max_age():
    """Gültigkeit des Opt-in-Tokens in Sekunden.

    Dieselbe Zahl steuert die Löschfrist unbestätigter Einträge — zwei getrennte
    Werte würden auseinanderdriften und einen toten Link auf eine noch
    existierende Zeile ergeben.
    """
    return max(1, get_config_int("MAILINGLISTE_OPTIN_TAGE", 7)) * 24 * 3600


def make_optin_token(abo_pk):
    return _optin_signer.sign(str(abo_pk))


def read_optin_token(token):
    """Abo-PK aus einem gültigen Token, sonst None (ungültig oder abgelaufen)."""
    try:
        return int(_optin_signer.unsign(token, max_age=optin_max_age()))
    except (BadSignature, SignatureExpired, ValueError):
        return None


def optin_url(base_url, abo):
    token = make_optin_token(abo.pk)
    return f"{base_url.rstrip('/')}/auftritte/bestaetigen/{token}/"


def _fingerabdruck(email):
    """Kurzer Hash der Adresse für den Abmelde-Token.

    Primärschlüssel werden nach dem Löschen wiederverwendet (SQLite vergibt
    ohne AUTOINCREMENT schlicht ``max(rowid)+1``). Ohne diesen Zusatz könnte
    ein alter Abmelde-Link aus einer längst verschickten Mail einen inzwischen
    neu angelegten, fremden Eintrag treffen.
    """
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]


def make_abmelde_token(abo):
    """Signierter Abmelde-Token — bewusst ohne Zeitstempel.

    Der Link steht in jeder Mail und muss unbefristet gültig bleiben. Signiert
    wird ``<pk>-<fingerabdruck>``; die Adresse selbst gehört nicht in eine URL,
    sie landete sonst in Server-Logs, Referrern und der Browser-Chronik.
    """
    return _abmelde_signer.sign(f"{abo.pk}-{_fingerabdruck(abo.email)}")


def lese_abmelde_token(token):
    """``(pk, fingerabdruck)`` aus einem gültigen Token, sonst None.

    Reine Funktion ohne Datenbankzugriff — dadurch ohne Testdatenbank prüfbar.
    """
    try:
        roh = _abmelde_signer.unsign(token)
    except BadSignature:
        return None
    pk, _, fingerabdruck = roh.partition("-")
    try:
        return int(pk), fingerabdruck
    except (TypeError, ValueError):
        return None


def read_abmelde_token(token):
    """Das Abo zu einem gültigen Token, sonst None."""
    from intern.models import Auftrittsabo

    gelesen = lese_abmelde_token(token)
    if gelesen is None:
        return None
    pk, fingerabdruck = gelesen
    abo = Auftrittsabo.objects.filter(pk=pk).first()
    if abo is None or _fingerabdruck(abo.email) != fingerabdruck:
        return None
    return abo


def abmelde_url(base_url, abo):
    return f"{base_url.rstrip('/')}/auftritte/abmelden/{make_abmelde_token(abo)}/"


def basis_url():
    """Öffentliche Basis-URL aus der Konfiguration, oder "" wenn nicht gesetzt.

    Ohne sie darf nicht versandt werden — ein relativer und damit toter
    Abmelde-Link wäre rechtlich nicht vertretbar.
    """
    return get_base_url()


# ---------------------------------------------------------------------------
# Fälligkeit
# ---------------------------------------------------------------------------

def parse_wochen(roh_liste=None):
    """Vorlaufzeiten aus ``MAILINGLISTE_WOCHEN`` als absteigende Liste von ints.

    Unsinnige Einträge werden still verworfen, Duplikate entfernt — die
    Konfiguration ist von Hand editierbar und darf den Dauerloop nicht kippen.
    """
    if roh_liste is None:
        roh_liste = get_config_list("MAILINGLISTE_WOCHEN", "4,1")
    werte = set()
    for teil in roh_liste:
        try:
            zahl = int(str(teil).strip())
        except (ValueError, TypeError):
            continue
        if zahl >= 0:
            werte.add(zahl)
    return sorted(werte, reverse=True)


def versandzeit():
    """``MAILINGLISTE_VERSANDZEIT`` als ``time`` — nur Fallback, siehe faelligkeit()."""
    roh = (get_config("MAILINGLISTE_VERSANDZEIT") or "18:00").strip()
    try:
        stunde, _, minute = roh.partition(":")
        return time(int(stunde), int(minute or 0))
    except (ValueError, TypeError):
        return time(18, 0)


def faelligkeit(termin, wochen, fallback_zeit):
    """Zeitpunkt, zu dem die Erinnerung mit ``wochen`` Vorlauf fällig wird.

    Exakt N Wochen vor dem Termin zur selben Uhrzeit — damit automatisch am
    selben Wochentag.  Termine ohne bekannte Uhrzeit (00:00) fallen auf die
    konfigurierte Versandzeit zurück, sonst ginge die Mail nachts raus.
    """
    ziel = termin.datum - timedelta(weeks=wochen)
    if termin.datum.time() == time(0, 0):
        ziel = datetime.combine(ziel.date(), fallback_zeit)
    return ziel


def faellige_erinnerungen(termine, wochen_liste, jetzt, fallback_zeit,
                          kulanz_stunden=KULANZ_STUNDEN):
    """Alle jetzt fälligen ``(termin, wochen, faellig_am)`` — sortiert nach Fälligkeit.

    Fällig ist ein Paar, wenn der Zeitpunkt erreicht, aber nicht länger als
    ``kulanz_stunden`` her ist und der Termin noch bevorsteht.  Reine Funktion:
    ``jetzt`` kommt von außen.
    """
    kulanz = timedelta(hours=kulanz_stunden)
    treffer = []
    for termin in termine:
        if termin.datum < jetzt:
            continue
        for wochen in wochen_liste:
            faellig = faelligkeit(termin, wochen, fallback_zeit)
            if faellig <= jetzt <= faellig + kulanz:
                treffer.append((termin, wochen, faellig))
    treffer.sort(key=lambda t: t[2])
    return treffer


# ---------------------------------------------------------------------------
# Platzhalter
# ---------------------------------------------------------------------------

def termin_platzhalter(termin, wochen):
    """Platzhalter für ``MAIL_MAILINGLISTE_ERINNERUNG``.

    Bewusst **kein** ``{beschreibung}``: ``mail_markup`` setzt Platzhalter vor
    dem Zeilen-Parsing ein, ein mehrzeiliges ``Termin.lang`` könnte damit einen
    ``{button:…:URL}`` in eine Mail an die Öffentlichkeit schmuggeln.
    ``Termin.kurz`` (einzeilig, max. 64) und ``Ort.name`` sind unkritisch.

    Wochentagsnamen kommen aus einem eigenen Tupel und nicht aus
    ``replacements.format_datetime`` — das ruft ``locale.setlocale()`` und wäre
    prozessglobaler Zustand in einem Dauerloop.
    """
    datum = termin.datum
    hat_uhrzeit = datum.time() != time(0, 0)
    uhrzeit = datum.strftime("%H:%M") if hat_uhrzeit else ""
    ort = termin.ort
    adresse = ""
    if ort:
        adresse = " ".join(
            teil for teil in [ort.strasse, f"{ort.plz or ''} {ort.ort or ''}".strip()]
            if teil
        ).strip()
    return {
        "titel":        termin.kurz,
        "datum":        datum.strftime("%d.%m.%Y"),
        "wochentag":    _WOCHENTAGE[datum.weekday()],
        "uhrzeit":      uhrzeit,
        "uhrzeit_text": f" um {uhrzeit} Uhr" if hat_uhrzeit else "",
        "ort":          ort.name if ort else "",
        "ort_adresse":  adresse,
        "wochen":       str(wochen),
        "wochen_text":  wochen_text(wochen),
    }


def wochen_text(wochen):
    if wochen == 0:
        return "heute"
    if wochen == 1:
        return "einer Woche"
    return f"{_ZAHLWORT.get(wochen, wochen)} Wochen"


# ---------------------------------------------------------------------------
# Versand
# ---------------------------------------------------------------------------

def send_mailingliste_mail(subject, abo, key, base_url, link=None, **extra):
    """Verschickt einen ``MAIL_MAILINGLISTE_*``-Text an genau einen Empfänger.

    Der Abmelde-Link ist hier fest verdrahtet und damit **nicht
    wegkonfigurierbar**: er steht als ``List-Unsubscribe``-Header, als Zeile im
    Plain-Text-Teil und über das Template im HTML-Teil — unabhängig davon, was
    im Konfigurationstext steht.

    ``List-Unsubscribe-Post`` wird bewusst nicht gesetzt: der Provider schickt
    dann einen unauthentifizierten POST, den die CSRF-Middleware verwirft.

    ``link`` ist das Ziel für ``{button:…}`` im Konfigurationstext; ohne Angabe
    zeigt der Button auf den Abmelde-Link.
    """
    url = abmelde_url(base_url, abo)
    name = abo.name or ""
    body_html, plain = render_config_mail(
        key, link=link or url, abmelden=url, name=name,
        # Der Name ist optional; {name_anrede} ist " Vorname" oder leer, damit
        # "Hallo{name_anrede}," in beiden Fällen sauber liest.
        name_anrede=f" {name}" if name else "",
        email=abo.email, **extra
    )
    # Vor dem "-- "-Trenner, den send_branded_mail für den Footer anhängt.
    plain = f"{plain.rstrip()}\n\nKeine Erinnerungen mehr? Hier austragen: {url}\n"
    return send_branded_mail(
        subject,
        abo.email,
        "emails/mailingliste.html",
        {"body_html": body_html, "abmelde_url": url},
        text_body=plain,
        headers={
            "List-Unsubscribe":
                f"<{url}>, <mailto:{get_from_email()}?subject=unsubscribe>",
        },
    )


def cleanup_unbestaetigte(jetzt=None):
    """Löscht unbestätigte Anmeldungen nach Ablauf der Opt-in-Frist.

    Gibt die Anzahl gelöschter Zeilen zurück.  Läuft auch dann, wenn kein
    Mailversand konfiguriert ist — die Aufbewahrung hängt nicht am Versand.
    """
    from intern.models import Auftrittsabo

    jetzt = jetzt or timezone.now()
    grenze = jetzt - timedelta(seconds=optin_max_age())
    anzahl, _ = Auftrittsabo.objects.filter(
        bestaetigt_am__isnull=True, angemeldet_am__lt=grenze
    ).delete()
    if anzahl:
        logger.info("Mailingliste: %d unbestätigte Anmeldungen gelöscht", anzahl)
    return anzahl
