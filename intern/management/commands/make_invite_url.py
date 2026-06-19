from django.core.management.base import BaseCommand

from intern.app_settings import get_config
from intern.views.auth import make_invite_token


class Command(BaseCommand):
    help = (
        "Erzeugt einen signierten 7-Tage-Einladungslink für das Neuantrags-Formular "
        "(/intern/beitritt/<token>/) und gibt ihn aus."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "email",
            metavar="EMAIL",
            help="E-Mail-Adresse, die in den Einladungslink eingebettet wird.",
        )
        parser.add_argument(
            "--base-url",
            default=None,
            metavar="URL",
            help=(
                "Basis-URL des Portals (Schema + Host), z. B. https://portal.example.com. "
                "Standard: PORTAL_URL aus der Konfiguration, sonst http://localhost:8000"
            ),
        )

    def handle(self, *args, **options):
        email = options["email"]
        base_url = (options["base_url"] or get_config("PORTAL_URL", "") or "http://localhost:8000").rstrip("/")
        token = make_invite_token(email)
        self.stdout.write(f"{base_url}/intern/beitritt/{token}/")
