"""Schreibt den Datenbankstand nach ``sicherung/`` im Datenverzeichnis.

Einzeldurchlauf ist der Standard und sichert sofort; ``--loop`` ist der
Dauerbetrieb für ``start.sh`` und sichert, sobald seit der letzten Sicherung
``SICHERUNG_STUNDEN`` vergangen sind. Die Logik steht in ``intern/sicherung.py``.
"""

import logging
import time as _time
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from intern.app_settings import get_config_int
from intern.sicherung import DATEINAME, faellig, letzte_sicherung, sichern, verzeichnis

logger = logging.getLogger(__name__)

# Wie oft der Dauerbetrieb nachsieht. Kurz genug, dass eine geänderte
# SICHERUNG_STUNDEN bald greift; die Prüfung selbst liest nur stand.json.
PRUEFTAKT_S = 600


class Command(BaseCommand):
    help = (
        "Schreibt den Datenbankstand als SQLite-Datei nach sicherung/ im "
        "Datenverzeichnis. Ohne --loop genau eine Sicherung, sofort."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop", action="store_true",
            help="Dauerbetrieb: sichern, sobald SICHERUNG_STUNDEN vergangen sind.",
        )

    def handle(self, *args, **options):
        if not options["loop"]:
            stand = sichern(datetime.now())
            if stand:
                self.stdout.write(self.style.SUCCESS(
                    f"{sum(stand['zeilen'].values())} Zeilen nach "
                    f"{verzeichnis() / DATEINAME} gesichert."
                ))
            return

        while True:
            # Abgesichert wie die anderen Dauerprozesse: eine Ausnahme soll die
            # nächste Sicherung nicht verhindern.
            try:
                close_old_connections()
                jetzt = datetime.now()
                if faellig(letzte_sicherung(), jetzt,
                           get_config_int("SICHERUNG_STUNDEN", 24)):
                    sichern(jetzt)
            except Exception:
                logger.exception("Sicherung fehlgeschlagen")
            _time.sleep(PRUEFTAKT_S)
