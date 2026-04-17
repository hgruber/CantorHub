import threading

from django.apps import AppConfig
from django.db.models.signals import post_migrate, post_save, pre_migrate

# Thread-local for tracking migration status
_migrating = threading.local()


class InternConfig(AppConfig):
    name = "intern"

    def ready(self):
        def _start_migration(sender, **kwargs):
            _migrating.active = True

        def _end_migration(sender, **kwargs):
            _migrating.active = False

        pre_migrate.connect(_start_migration, dispatch_uid="intern_start_migration")
        post_migrate.connect(_end_migration, dispatch_uid="intern_end_migration")

        from . import signals  # noqa: F401
