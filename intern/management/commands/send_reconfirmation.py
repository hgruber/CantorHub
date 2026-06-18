from django.core.management.base import BaseCommand

from intern.models import User
from intern.views.auth import make_bestaetigung_url, send_bestaetigung_mail


class Command(BaseCommand):
    help = (
        "Sendet die Datenbestätigungs-E-Mail an einzelne oder alle aktiven Mitglieder. "
        "Die E-Mail enthält einen 30 Tage gültigen Link zum öffentlichen Bestätigungsformular. "
        "Mit --print-url wird nur die URL ausgegeben, ohne Mail zu senden."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--user",
            metavar="USERNAME",
            help="Benutzername des Mitglieds, an das die Mail gesendet werden soll.",
        )
        group.add_argument(
            "--all",
            action="store_true",
            dest="all_users",
            help="Mail an alle aktiven Mitglieder mit hinterlegter E-Mail-Adresse senden.",
        )
        parser.add_argument(
            "--base-url",
            default="http://localhost:8000",
            metavar="URL",
            help=(
                "Basis-URL des Portals (Schema + Host), z. B. https://portal.example.com. "
                "Standard: http://localhost:8000"
            ),
        )
        parser.add_argument(
            "--print-url",
            action="store_true",
            dest="print_url",
            help="Nur URL ausgeben, keine Mail senden.",
        )

    def handle(self, *args, **options):
        base_url = options["base_url"]
        print_url = options["print_url"]

        if options["user"]:
            try:
                user = User.objects.get(username=options["user"], is_active=True)
            except User.DoesNotExist:
                self.stderr.write(
                    self.style.ERROR(
                        f"Benutzer '{options['user']}' nicht gefunden oder inaktiv."
                    )
                )
                return
            if print_url:
                self.stdout.write(make_bestaetigung_url(user, base_url))
            else:
                self._send(user, base_url)
        else:
            users = User.objects.filter(is_active=True).exclude(email="").order_by("username")
            if print_url:
                for user in users:
                    self.stdout.write(f"{user.username}\t{make_bestaetigung_url(user, base_url)}")
            else:
                count = users.count()
                self.stdout.write(f"Sende an {count} Mitglieder …")
                for user in users:
                    self._send(user, base_url)

    def _send(self, user, base_url):
        try:
            send_bestaetigung_mail(user, base_url)
            self.stdout.write(self.style.SUCCESS(f"OK   {user.username} <{user.email}>"))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"ERR  {user.username}: {exc}"))
