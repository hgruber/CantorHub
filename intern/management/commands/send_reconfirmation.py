from django.core.management.base import BaseCommand

from intern.app_settings import get_base_url, konfiguration_gepuffert
from intern.mitgliedschaft import GRUPPE_MITGLIED, ist_mitglied
from intern.models import User
from intern.views.auth import (
    make_bestaetigung_url,
    send_bestaetigung_mail,
    sperre_bis_bestaetigung,
)


class Command(BaseCommand):
    help = (
        "Sendet die Datenbestätigungs-E-Mail an einzelne oder alle aktiven Mitglieder. "
        "Die E-Mail enthält einen 30 Tage gültigen Link zum öffentlichen Bestätigungsformular. "
        "Nach dem Versand ist der Portalzugang bis zur Bestätigung gesperrt. "
        "Mit --print-url wird nur die URL ausgegeben, ohne Mail zu senden; gesperrt wird "
        "trotzdem, denn ein aktives Konto gilt als bestätigt und der Link wäre wertlos. "
        "Nur Konten mit dem Tag „Mitglied“ — ohne Tag weist das Formular den Link ab."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--user",
            metavar="USERNAME",
            help=(
                "Benutzername des Mitglieds, an das die Mail gesendet werden soll — "
                "auch ein bereits gesperrtes, etwa nach Ablauf des Links."
            ),
        )
        group.add_argument(
            "--all",
            action="store_true",
            dest="all_users",
            help=(
                "Mail an alle aktiven Konten mit Tag „Mitglied“ und hinterlegter "
                "E-Mail-Adresse senden."
            ),
        )
        parser.add_argument(
            "--base-url",
            default=None,
            metavar="URL",
            help=(
                "Basis-URL des Portals (Schema + Host), z. B. https://portal.example.com. "
                "Standard: VEREINS_URL aus der Konfiguration, sonst http://localhost:8000"
            ),
        )
        parser.add_argument(
            "--print-url",
            action="store_true",
            dest="print_url",
            help="Nur URL ausgeben, keine Mail senden. Sperrt das Konto wie der Versand.",
        )

    def handle(self, *args, **options):
        base_url = get_base_url(options["base_url"], fallback="http://localhost:8000")
        print_url = options["print_url"]

        if options["user"]:
            try:
                user = User.objects.get(username=options["user"])
            except User.DoesNotExist:
                self.stderr.write(
                    self.style.ERROR(f"Benutzer '{options['user']}' nicht gefunden.")
                )
                return
            if not ist_mitglied(user):
                self.stderr.write(self.style.ERROR(
                    f"'{user.username}' trägt das Tag „{GRUPPE_MITGLIED}“ nicht — "
                    "der Link würde abgewiesen. Nichts gesendet, nichts gesperrt."
                ))
                return
            if print_url:
                self.stdout.write(make_bestaetigung_url(user, base_url))
                sperre_bis_bestaetigung(user)
            else:
                self._send(user, base_url)
        else:
            users = (
                User.objects.filter(is_active=True, groups__name=GRUPPE_MITGLIED)
                .exclude(email="")
                .order_by("username")
            )
            if print_url:
                for user in users:
                    self.stdout.write(f"{user.username}\t{make_bestaetigung_url(user, base_url)}")
                    sperre_bis_bestaetigung(user)
            else:
                count = users.count()
                self.stdout.write(f"Sende an {count} Mitglieder …")
                # Ein Puffer fuer den ganzen Versand: jede Mail liest sonst
                # sechzehn Konfigurationswerte neu, die sich hier nicht aendern.
                with konfiguration_gepuffert():
                    for user in users:
                        self._send(user, base_url)

    def _send(self, user, base_url):
        try:
            send_bestaetigung_mail(user, base_url)
            self.stdout.write(self.style.SUCCESS(f"OK   {user.username} <{user.email}>"))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"ERR  {user.username}: {exc}"))
