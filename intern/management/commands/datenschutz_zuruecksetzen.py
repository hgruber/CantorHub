from django.core.management.base import BaseCommand

from intern.mitgliedschaft import GRUPPE_DATENSCHUTZ_BESTAETIGT, setze_datenschutz_bestaetigt
from intern.models import User


class Command(BaseCommand):
    help = (
        "Entfernt das Tag „DSGVO“ — einzeln oder bei allen. Konten mit "
        "Zugang ohne Mitgliedschaft sehen danach beim nächsten Seitenaufruf wieder die "
        "Seite „Datenschutz bestätigen“, etwa nach einer geänderten Datenschutzerklärung."
    )

    def add_arguments(self, parser):
        gruppe = parser.add_mutually_exclusive_group(required=True)
        gruppe.add_argument("--user", metavar="USERNAME", help="Nur dieses Konto.")
        gruppe.add_argument(
            "--all", action="store_true", dest="alle", help="Alle Konten mit dem Tag."
        )

    def handle(self, *args, **options):
        konten = User.objects.filter(groups__name=GRUPPE_DATENSCHUTZ_BESTAETIGT)
        if options["user"]:
            konten = konten.filter(username=options["user"])
            if not konten.exists():
                self.stderr.write(self.style.ERROR(
                    f"'{options['user']}' trägt das Tag „{GRUPPE_DATENSCHUTZ_BESTAETIGT}“ nicht."
                ))
                return
        anzahl = 0
        for user in konten.order_by("username"):
            setze_datenschutz_bestaetigt(user, False)
            self.stdout.write(f"zurückgesetzt  {user.username}")
            anzahl += 1
        self.stdout.write(self.style.SUCCESS(f"{anzahl} Konto/Konten zurückgesetzt."))
