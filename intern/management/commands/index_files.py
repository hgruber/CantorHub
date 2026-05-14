"""Build the per-file text search index for all files.

Run after setup (migrate.sh / start.sh) so the first content search does not
have to extract text from every file synchronously.
"""

from django.core.management.base import BaseCommand
from filer.models import File

from intern.fileindex import index_file


class Command(BaseCommand):
    help = "Build the per-file text search index for all files."

    def handle(self, *args, **options):
        total = File.objects.count()
        done = 0
        for f in File.objects.all().iterator():
            try:
                index_file(f)
            except Exception as exc:
                self.stderr.write(f"  Fehler bei Datei {f.pk}: {exc}")
            done += 1
            if done % 50 == 0:
                self.stdout.write(f"  {done}/{total} indiziert …")
        self.stdout.write(
            self.style.SUCCESS(f"{done}/{total} Dateien indiziert.")
        )
