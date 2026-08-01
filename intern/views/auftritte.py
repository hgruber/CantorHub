"""Öffentliche Views der Auftritts-Mailingliste (kein Login).

Anmeldung mit Double-Opt-in, Bestätigung und Abmeldung.  Die Domänenlogik
(Tokens, URLs, Versand) liegt in ``intern/mailingliste.py``.
"""

import logging
from datetime import timedelta

from django.core.cache import cache
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from intern.app_settings import get_config, is_email_configured
from intern.forms import AuftrittsaboForm
from intern.mailingliste import (
    OPTIN_COOLDOWN_MIN,
    optin_url,
    read_optin_token,
    send_mailingliste_mail,
)
from intern.models import Auftrittsabo

from .auth import _client_ip

logger = logging.getLogger(__name__)

# Wie register(): eine Bremse pro IP. CACHES ist nicht konfiguriert, also
# LocMemCache und damit pro gunicorn-Worker — die verlässliche Bremse gegen
# Mail-Bombing ist der DB-gestützte Cooldown über optin_gesendet_am.
_MAX_PRO_STUNDE = 10


def _status(request, titel, text, ok=True, status=200):
    """Eine parametrisierte Ergebnisseite für alle Ausgänge der drei Views."""
    return render(request, "auftritte_status.html",
                  {"titel": titel, "text": text, "ok": ok}, status=status)


def _base_url(request):
    """Öffentliche Basis-URL aus der Anfrage — wie in mitglied_beitritt."""
    return f"{request.scheme}://{request.get_host()}"


def auftritte_anmeldung(request):
    """Öffentliches Anmeldeformular für die Auftritts-Mailingliste.

    Antwortet bei einer bereits eingetragenen Adresse **identisch** wie bei
    einer neuen — sonst könnte jeder testen, wer im Verteiler steht.  Verzweigt
    wird nur im Mailversand (Muster: ``register()``).
    """
    text = get_config("MAILINGLISTE_TEXT", "")

    if request.method != "POST":
        return render(request, "auftritte_anmeldung.html",
                      {"form": AuftrittsaboForm(), "text": text})

    # Honeypot vor allem anderen: Bots bekommen die Erfolgsseite, sonst nichts.
    if request.POST.get("webseite"):
        return _erfolgsseite(request)

    form = AuftrittsaboForm(request.POST)
    throttle_key = f"mailingliste-throttle:{_client_ip(request)}"
    versuche = cache.get(throttle_key, 0)
    if versuche >= _MAX_PRO_STUNDE:
        form.add_error(None, "Zu viele Anfragen. Bitte versuche es später erneut.")
        return render(request, "auftritte_anmeldung.html",
                      {"form": form, "text": text})

    if not form.is_valid():
        return render(request, "auftritte_anmeldung.html",
                      {"form": form, "text": text})

    cache.set(throttle_key, versuche + 1, 3600)
    _anmeldung_verarbeiten(request, form)
    return _erfolgsseite(request)


def _anmeldung_verarbeiten(request, form):
    """Legt den Eintrag an (oder nicht) und verschickt die passende Mail.

    Trennt bewusst die Seiten-Antwort von der Verarbeitung: die Seite ist
    immer dieselbe, nur hier wird unterschieden.
    """
    jetzt = timezone.now()
    base_url = _base_url(request)
    abo, neu = Auftrittsabo.objects.get_or_create(
        email=form.cleaned_data["email"],
        defaults={
            "name": form.cleaned_data.get("name", ""),
            "angemeldet_ip": _client_ip(request) or None,
            "einwilligungstext": form.einwilligungstext,
        },
    )

    if abo.bestaetigt:
        # Adresse steht schon im Verteiler — Hinweis mit Abmelde-Link statt
        # eines zweiten Opt-ins, aber nur innerhalb des Cooldowns gedrosselt.
        if _cooldown_abgelaufen(abo, jetzt):
            abo.optin_gesendet_am = jetzt
            abo.save(update_fields=["optin_gesendet_am"])
            send_mailingliste_mail(
                "Du stehst bereits auf unserer Auftritts-Liste",
                abo, "MAIL_MAILINGLISTE_BEREITS_ANGEMELDET", base_url,
            )
        return

    if not _cooldown_abgelaufen(abo, jetzt):
        return

    if not neu:
        # Erneuter Anlauf vor der Bestätigung: Name und Einwilligungstext
        # auffrischen, der Eintrag ist noch nicht wirksam.
        abo.name = form.cleaned_data.get("name", "") or abo.name
        abo.einwilligungstext = form.einwilligungstext
        abo.angemeldet_ip = _client_ip(request) or abo.angemeldet_ip

    link = optin_url(base_url, abo)
    abo.optin_gesendet_am = jetzt
    abo.save()

    if not is_email_configured():
        # Ohne Mailkonfiguration ist die URL sonst nirgends sichtbar:
        # send_branded_mail baut die MIME-Nachricht selbst und übergibt dem
        # Konsolen-Backend einen leeren Body.
        logger.info("Mailingliste: Opt-in-Link für %s: %s", abo.email, link)

    send_mailingliste_mail(
        "Bitte bestätige Deine Anmeldung",
        abo, "MAIL_MAILINGLISTE_OPTIN", base_url, link=link,
    )


def _cooldown_abgelaufen(abo, jetzt):
    """True, wenn seit der letzten Mail an diese Adresse genug Zeit vergangen ist."""
    if abo.optin_gesendet_am is None:
        return True
    return abo.optin_gesendet_am < jetzt - timedelta(minutes=OPTIN_COOLDOWN_MIN)


def _erfolgsseite(request):
    return _status(
        request,
        "Fast geschafft",
        "Wenn Deine Adresse noch nicht bei uns liegt, haben wir Dir gerade eine "
        "E-Mail mit einem Bestätigungslink geschickt. Erst nach dem Klick auf "
        "diesen Link tragen wir Dich ein.",
    )


@require_http_methods(["GET", "POST"])
def auftritte_bestaetigen(request, token):
    """Zweiter Schritt des Double-Opt-ins.

    GET zeigt nur einen Button, erst POST bestätigt.  Grund: Outlook SafeLinks
    und Virenscanner rufen Links vorab per GET auf und würden die Einwilligung
    ohne menschlichen Klick dokumentieren — das zerstört den Nachweiswert.
    """
    abo_pk = read_optin_token(token)
    abo = Auftrittsabo.objects.filter(pk=abo_pk).first() if abo_pk else None
    if abo is None:
        return _status(
            request,
            "Link ungültig oder abgelaufen",
            "Dieser Bestätigungslink ist nicht (mehr) gültig. Trage Dich einfach "
            "erneut ein, dann schicken wir Dir einen frischen Link.",
            ok=False, status=400,
        )

    if request.method == "GET" and not abo.bestaetigt:
        return render(request, "auftritte_bestaetigen.html", {"abo": abo})

    if not abo.bestaetigt:
        abo.bestaetigt = True
        abo.bestaetigt_am = timezone.now()
        abo.bestaetigt_ip = _client_ip(request) or None
        abo.save(update_fields=["bestaetigt", "bestaetigt_am", "bestaetigt_ip"])
        send_mailingliste_mail(
            "Willkommen auf unserer Auftritts-Liste",
            abo, "MAIL_MAILINGLISTE_WILLKOMMEN", _base_url(request),
        )

    # Auch beim zweiten Klick dieselbe Seite — die Aktion ist idempotent.
    return _status(
        request,
        "Eintrag bestätigt",
        "Danke! Wir melden uns rechtzeitig vor jedem öffentlichen Auftritt — "
        "und sonst nicht. Abmelden kannst Du Dich über den Link in jeder E-Mail.",
    )


@require_http_methods(["GET", "POST"])
def auftritte_abmelden(request, token):
    """Abmeldung: GET zeigt einen Button, POST löscht die Zeile.

    Gelöscht wird wirklich — eine gespeicherte Adresse ohne Einwilligung wäre
    selbst eine Verarbeitung.  Ein unbekanntes Token ist der Normalfall beim
    zweiten Klick und darf deshalb keinen Fehler zeigen.
    """
    abo = Auftrittsabo.objects.filter(abmelde_token=token).first()
    if abo is None:
        return _status(
            request,
            "Nicht in unserem Verteiler",
            "Diese Adresse steht nicht (mehr) auf unserer Auftritts-Liste. "
            "Du musst nichts weiter tun.",
        )

    if request.method == "GET":
        return render(request, "auftritte_abmelden.html", {"abo": abo})

    abo.delete()
    return _status(
        request,
        "Abgemeldet",
        "Wir haben Deine Adresse gelöscht und schicken Dir keine Erinnerungen "
        "mehr. Du kannst Dich jederzeit wieder eintragen.",
    )
