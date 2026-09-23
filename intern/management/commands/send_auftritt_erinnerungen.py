"""Verschickt die Erinnerungen der öffentlichen Auftritts-Mailingliste.

Einzeldurchlauf ist der Standard, ``--loop`` der Dauerbetrieb für ``start.sh``
(analog ``ejabberd_bot``).  Andersherum würde ein interaktiver Testaufruf
versehentlich einen zweiten Daemon starten.
"""

import logging
import time as _time
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from intern.app_settings import (
    get_config_int,
    is_email_configured,
    konfiguration_gepuffert,
)
from intern.mailingliste import (
    basis_url,
    cleanup_unbestaetigte,
    faellige_erinnerungen,
    parse_wochen,
    send_mailingliste_mail,
    termin_platzhalter,
    versandzeit,
)
from intern.models import Auftrittsabo, ErinnerungVersand, OHNE_ANKUENDIGUNG, Termin

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Verschickt Erinnerungen an öffentlich angekündigte Auftritte (Termine mit "
        "Ankündigungstext, Termin.extern) an die bestätigten Adressen der "
        "Auftritts-Mailingliste. Ohne --loop läuft genau ein Durchlauf."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop", action="store_true",
            help="Dauerbetrieb: alle MAILINGLISTE_INTERVALL_MIN Minuten prüfen.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", dest="dry_run",
            help="Nur anzeigen, was fällig wäre — kein Marker, keine Mail.",
        )
        parser.add_argument(
            "--now", metavar="ISO8601", default=None,
            help="'Jetzt' überschreiben (z. B. 2026-09-01T20:00:00) — für Tests.",
        )
        parser.add_argument(
            "--termin", type=int, metavar="ID", default=None,
            help="Nur diesen Termin betrachten.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Vorhandene Versand-Marker ignorieren (Nachversand nach Abbruch).",
        )

    def handle(self, *args, **options):
        # konfiguration_gepuffert() umschliesst genau einen Durchlauf: der Versand
        # liest pro Empfaenger sechzehn Konfigurationswerte (Vereinsname, Footer,
        # Absender), die sich waehrend eines Durchlaufs nicht aendern. Bewusst nicht
        # um die while-Schleife herum — sonst bliebe der Prozess bis zum Neustart auf
        # der Konfiguration seines Starts stehen, das Intervall unten eingeschlossen.
        if not options["loop"]:
            with konfiguration_gepuffert():
                self._iteration(options)
            return

        self.stdout.write("Auftritts-Erinnerungen: Dauerbetrieb gestartet.")
        while True:
            # Der komplette Rumpf ist abgesichert: start.sh startet den Prozess
            # mit '&', es gibt keinen Supervisor. Eine ungefangene Exception
            # wuerde den Versand still bis zum naechsten Neustart killen.
            try:
                with konfiguration_gepuffert():
                    self._iteration(options)
            except Exception:
                logger.exception("Auftritts-Erinnerungen: Durchlauf fehlgeschlagen")
            # Intervall pro Iteration neu lesen — die Konfiguration ist zur
            # Laufzeit ueber /intern/konfiguration/ aenderbar. Steht ausserhalb des
            # Puffers, damit eine Aenderung zwischen zwei Durchlaeufen ankommt.
            _time.sleep(max(1, get_config_int("MAILINGLISTE_INTERVALL_MIN", 10)) * 60)

    # ------------------------------------------------------------------
    def _iteration(self, options):
        # Ein Dauerloop haelt die DB-Verbindung sonst offen bis in MySQLs
        # wait_timeout ("MySQL server has gone away"); CONN_MAX_AGE greift nur
        # im Request-Zyklus.
        close_old_connections()

        jetzt = self._jetzt(options["now"])
        dry_run = options["dry_run"]

        # Aufraeumen laeuft immer — die Aufbewahrungsfrist haengt nicht am Versand.
        if not dry_run:
            cleanup_unbestaetigte(jetzt)

        termine = Termin.objects.filter(datum__gte=jetzt).exclude(OHNE_ANKUENDIGUNG)
        if options["termin"]:
            termine = termine.filter(pk=options["termin"])
        termine = list(termine.select_related("ort"))

        wochen_liste = parse_wochen()
        faellig = faellige_erinnerungen(termine, wochen_liste, jetzt, versandzeit())

        # Faelligkeit zuerst, Konfigurationspruefung danach: im Dauerbetrieb liefe
        # sonst alle MAILINGLISTE_INTERVALL_MIN Minuten dieselbe Warnung durchs Log,
        # obwohl die fehlende Konfiguration gerade gar keinen Versand verhindert.
        if not faellig:
            if termine and not wochen_liste:
                # Der einzige Fall, den die Faelligkeit selbst verschluckt:
                # faellige_erinnerungen() laeuft ueber wochen_liste, ohne Vorlaufzeit
                # wird also nie etwas faellig — die Meldung bliebe sonst fuer immer aus.
                self._warnen("MAILINGLISTE_WOCHEN ergibt keine gültigen Vorlaufzeiten.")
            else:
                self.stdout.write("0 Erinnerungen fällig.")
            return

        base_url = basis_url()
        if not base_url:
            self._warnen(
                "VEREINS_URL ist nicht gesetzt — kein Versand. Eine Mail mit "
                "relativem und damit totem Abmelde-Link wäre nicht vertretbar."
            )
            return
        if not is_email_configured():
            self._warnen("EMAIL_HOST ist nicht gesetzt — kein Versand.")
            return

        for termin, wochen, faellig_am in faellig:
            self._versenden(termin, wochen, faellig_am, base_url, options)

    def _versenden(self, termin, wochen, faellig_am, base_url, options):
        kopf = f"{termin.kurz} ({termin.datum:%d.%m.%Y %H:%M}), {wochen} Wochen Vorlauf"

        if options["dry_run"]:
            vorhanden = ErinnerungVersand.objects.filter(
                termin=termin, wochen=wochen
            ).exists()
            hinweis = " — Marker vorhanden" if vorhanden else ""
            self.stdout.write(f"[dry-run] fällig: {kopf}{hinweis}")
            return

        # Marker VOR dem Versand anlegen: der Unique-Constraint ist der einzige
        # Schutz gegen Doppelversand durch parallele Prozesse. Bewusst kein
        # transaction.atomic() um den Batch — der Marker muss sofort fuer andere
        # Prozesse sichtbar sein, und SMTP gehoert nie in eine offene Transaktion.
        marker, created = ErinnerungVersand.objects.get_or_create(
            termin=termin, wochen=wochen, defaults={"faellig_am": faellig_am}
        )
        if not created and not options["force"]:
            self.stdout.write(f"übersprungen (bereits versendet): {kopf}")
            return

        platzhalter = termin_platzhalter(termin, wochen)
        betreff = f"Erinnerung: {termin.kurz} am {platzhalter['datum']}"
        empfaenger = Auftrittsabo.objects.filter(
            bestaetigt_am__isnull=False
        ).order_by("pk")

        erfolge = 0
        for abo in empfaenger:
            if send_mailingliste_mail(
                betreff, abo, "MAIL_MAILINGLISTE_ERINNERUNG", base_url, **platzhalter
            ):
                erfolge += 1

        marker.empfaenger = erfolge
        marker.save(update_fields=["empfaenger"])
        self.stdout.write(self.style.SUCCESS(f"{erfolge} Mails versendet: {kopf}"))

    # ------------------------------------------------------------------
    def _jetzt(self, roh):
        if not roh:
            return timezone.now()
        # USE_TZ=False: naive lokale Wanduhrzeit, kein localtime().
        return datetime.fromisoformat(roh)

    def _warnen(self, text):
        self.stderr.write(self.style.WARNING(text))
        logger.warning("Auftritts-Erinnerungen: %s", text)
