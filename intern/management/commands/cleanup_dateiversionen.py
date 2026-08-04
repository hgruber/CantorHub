from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone
from easy_thumbnails.files import get_thumbnailer
from filer.models import File

from intern.app_settings import get_config_int
from intern.models import DateiVersion

# Alte Dateifassungen sind ein Komfort-Feature, kein Archiv: pro Datei bleiben
# die letzten Fassungen erhalten, ältere fallen nach der Frist weg.
DEFAULT_KEEP = 10
DEFAULT_RETENTION_DAYS = 2 * 365


class Command(BaseCommand):
    help = (
        "Löscht alte Dateiversionen samt ihrer Blobs: alles, was älter als die "
        "Aufbewahrungsfrist ist (Standard: 2 Jahre) oder über die Anzahl der pro "
        "Datei behaltenen Fassungen (Standard: 10) hinausgeht. Sollte regelmäßig "
        "laufen (z. B. bei jedem Server-Start)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            type=int,
            default=None,
            metavar="N",
            help="Fassungen, die je Datei behalten werden (Standard: aus "
            "Konfiguration DATEIVERSION_AUFBEWAHRUNG_ANZAHL, sonst 10).",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            metavar="N",
            help="Aufbewahrungsfrist in Tagen (Standard: aus Konfiguration "
            "DATEIVERSION_AUFBEWAHRUNG_TAGE, sonst 2 Jahre).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Nur zählen, nichts löschen.",
        )

    def _veraltet(self, keep, days):
        """Versionen, die entweder zu alt sind oder aus dem Behalten-Fenster
        herausgefallen sind."""
        cutoff = timezone.now() - timedelta(days=days)
        pks = set(
            DateiVersion.objects.filter(datum__lt=cutoff).values_list("pk", flat=True)
        )
        zu_viele = (
            DateiVersion.objects.values("aktuell")
            .annotate(anzahl=Count("pk"))
            .filter(anzahl__gt=keep)
            .values_list("aktuell", flat=True)
        )
        for pfad in zu_viele:
            ueberzaehlig = DateiVersion.objects.filter(aktuell=pfad).values_list(
                "pk", flat=True
            )[keep:]
            pks.update(ueberzaehlig)
        return DateiVersion.objects.filter(pk__in=pks)

    def handle(self, *args, **options):
        keep = options["keep"] if options["keep"] is not None else get_config_int(
            "DATEIVERSION_AUFBEWAHRUNG_ANZAHL", DEFAULT_KEEP
        )
        days = options["days"] if options["days"] is not None else get_config_int(
            "DATEIVERSION_AUFBEWAHRUNG_TAGE", DEFAULT_RETENTION_DAYS
        )
        qs = self._veraltet(keep, days)
        count = qs.count()

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] {count} Dateiversionen würden gelöscht "
                f"(älter als {days} Tage oder über {keep} Fassungen je Datei)."
            )
            return

        if not count:
            self.stdout.write("Keine veralteten Dateiversionen.")
            return

        # Storage über eine beliebige File-Instanz — alle Blobs liegen im
        # selben filer-Storage.
        muster = File.objects.first()
        storage = muster.file.storage if muster else None
        geloescht = 0
        for v in qs:
            if storage is not None:
                try:
                    get_thumbnailer(v.pfad).delete_thumbnails()
                except Exception:
                    pass
                try:
                    storage.delete(v.pfad)
                except Exception:
                    self.stderr.write(f"Blob {v.pfad} nicht löschbar.")
            geloescht += 1
        qs.delete()
        self.stdout.write(
            f"{geloescht} Dateiversionen gelöscht "
            f"(älter als {days} Tage oder über {keep} Fassungen je Datei)."
        )
