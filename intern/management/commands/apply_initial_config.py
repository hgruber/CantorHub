"""
Management command: apply_initial_config

Reads /app/initial.sh (if present) and upserts each KEY=VALUE pair into the
Konfiguration table.  Existing values are overwritten so the file is the
authoritative source on every (re)deploy.

Accepted line formats:
    KEY=value
    export KEY=value
    KEY="value with spaces"
    # comment lines and blank lines are ignored
"""

import logging
import re
from pathlib import Path

from django.core.management.base import BaseCommand

from intern.models import Konfiguration

logger = logging.getLogger(__name__)

_DEFAULT_PATHS = [
    Path("/app/initial.sh"),
    Path(__file__).resolve().parents[4] / "initial.sh",
]


def _parse(path: Path) -> dict[str, str]:
    result = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result


class Command(BaseCommand):
    help = "Apply key=value pairs from a shell config file to the Konfiguration table"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            dest="file",
            default=None,
            help="Path to the config file (default: tries /app/initial.sh then <project>/initial.sh)",
        )

    def handle(self, *args, **options):
        if options["file"]:
            candidates = [Path(options["file"])]
        else:
            candidates = _DEFAULT_PATHS

        config_file = next((p for p in candidates if p.exists()), None)
        if config_file is None:
            self.stdout.write("apply_initial_config: no config file found, skipping.")
            return

        self.stdout.write(f"apply_initial_config: reading {config_file}")
        entries = _parse(config_file)
        if not entries:
            self.stdout.write("apply_initial_config: file is empty or has no valid entries.")
            return

        for key, value in entries.items():
            _, created = Konfiguration.objects.update_or_create(
                key=key, defaults={"value": value}
            )
            verb = "created" if created else "updated"
            self.stdout.write(f"  {verb}: {key}")
            logger.info("apply_initial_config: %s %s", verb, key)

        self.stdout.write(f"apply_initial_config: applied {len(entries)} entries.")
