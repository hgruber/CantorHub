from filer.management.commands.import_files import Command as FilerImportCommand

from intern.apps import _migrating


class Command(FilerImportCommand):
    """Wraps filer's import_files and suppresses per-file index/thumbnail signals.

    Indexing and thumbnailing run as batch jobs (index_files / thumbnail_files)
    after the full import, so spawning one DB thread per file here is wasteful
    and can exhaust MySQL's connection limit when importing large directories.
    """

    def handle(self, *args, **options):
        _migrating.active = True
        try:
            super().handle(*args, **options)
        finally:
            _migrating.active = False
