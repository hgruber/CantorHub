from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from intern.app_settings import get_config_int
from intern.models import ErinnerungVersand

# Versand-Marker sind nur der Doppelversand-Schutz: sie werden nach Ablauf der
# Frist nicht mehr gebraucht (eine Erinnerung kann ohnehin nur vor dem Termin
# rausgehen). Default ein Jahr — länger ist uninteressant, kürzer ist möglich.
DEFAULT_RETENTION_DAYS = 365


class Command(BaseCommand):
    help = (
        "Löscht Versand-Marker (ErinnerungVersand), die älter als die "
        "Aufbewahrungsfrist sind. Sie dienen nur dem Doppelversand-Schutz und "
        "werden nach Ablauf nicht mehr gebraucht. Sollte regelmäßig laufen "
        "(z. B. bei jedem Server-Start)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            metavar="N",
            help="Aufbewahrungsfrist in Tagen (Standard: aus Konfiguration "
            "ERINNERUNG_VERSAND_AUFBEWAHRUNG_TAGE, sonst 1 Jahr).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Nur zählen, nichts löschen.",
        )

    def handle(self, *args, **options):
        days = options["days"] if options["days"] is not None else get_config_int(
            "ERINNERUNG_VERSAND_AUFBEWAHRUNG_TAGE", DEFAULT_RETENTION_DAYS
        )
        cutoff = timezone.now() - timedelta(days=days)
        qs = ErinnerungVersand.objects.filter(versendet_am__lt=cutoff)
        count = qs.count()

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] {count} Versand-Marker älter als {days} Tage "
                f"(vor {cutoff:%Y-%m-%d}) würden gelöscht."
            )
            return

        if count:
            qs.delete()
            self.stdout.write(
                f"{count} Versand-Marker älter als {days} Tage "
                f"(vor {cutoff:%Y-%m-%d}) gelöscht."
            )
        else:
            self.stdout.write(f"Keine Versand-Marker älter als {days} Tage.")