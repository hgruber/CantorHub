from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from intern.app_settings import get_config_int
from intern.models import ChangeLog

# Datenschutzerklärung §9: Das Änderungsprotokoll wird 3 Jahre aufbewahrt und
# anschließend gelöscht (Amtszeit Vorstand + Puffer; § 195 BGB).
DEFAULT_RETENTION_DAYS = 3 * 365


class Command(BaseCommand):
    help = (
        "Löscht Änderungsprotokoll-Einträge (ChangeLog), die älter als die "
        "Aufbewahrungsfrist sind (Standard: 3 Jahre, gemäß Datenschutzerklärung §9). "
        "Sollte regelmäßig laufen (z. B. bei jedem Server-Start)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            metavar="N",
            help="Aufbewahrungsfrist in Tagen (Standard: aus Konfiguration "
            "AENDERUNGSPROTOKOLL_AUFBEWAHRUNG_TAGE, sonst 3 Jahre).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Nur zählen, nichts löschen.",
        )

    def handle(self, *args, **options):
        days = options["days"] if options["days"] is not None else get_config_int(
            "AENDERUNGSPROTOKOLL_AUFBEWAHRUNG_TAGE", DEFAULT_RETENTION_DAYS
        )
        cutoff = timezone.now() - timedelta(days=days)
        qs = ChangeLog.objects.filter(timestamp__lt=cutoff)
        count = qs.count()

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] {count} Änderungsprotokoll-Einträge älter als "
                f"{days} Tage (vor {cutoff:%Y-%m-%d}) würden gelöscht."
            )
            return

        if count:
            qs.delete()
            self.stdout.write(
                f"{count} Änderungsprotokoll-Einträge älter als {days} Tage "
                f"(vor {cutoff:%Y-%m-%d}) gelöscht."
            )
        else:
            self.stdout.write(
                f"Keine Änderungsprotokoll-Einträge älter als {days} Tage."
            )
