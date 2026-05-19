"""Pre-generate easy-thumbnails for all thumbnailable filer files.

Run after setup (migrate.sh / start.sh) so the folder browser and article
previews do not have to generate thumbnails on first request.
"""

from django.core.management.base import BaseCommand
from easy_thumbnails.files import get_thumbnailer
from filer.models import File

_SIZES = [
    {"size": (32, 32), "crop": True, "quality": 85},
    {"size": (120, 120), "crop": True, "quality": 85},
    {"size": (200, 200), "quality": 85},
]


def _is_thumbnailable(mime):
    if not mime:
        return False
    return mime.startswith("image") or mime.endswith("pdf")


class Command(BaseCommand):
    help = "Pre-generate thumbnails for all image and PDF files."

    def handle(self, *args, **options):
        qs = File.objects.exclude(mime_type="").exclude(mime_type__isnull=True)
        candidates = [f for f in qs.iterator() if _is_thumbnailable(f.mime_type)]
        total = len(candidates)
        done = 0
        errors = 0
        for f in candidates:
            for opts in _SIZES:
                try:
                    get_thumbnailer(f.file).get_thumbnail(opts)
                except Exception:
                    errors += 1
            done += 1
            if done % 50 == 0:
                self.stdout.write(f"  {done}/{total} thumbnails generiert …")
        self.stdout.write(
            self.style.SUCCESS(
                f"{done}/{total} Dateien thumbnailed"
                + (f" ({errors} Fehler)" if errors else "") + "."
            )
        )
