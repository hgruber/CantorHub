from django.core.management.base import BaseCommand

from intern.app_settings import get_base_url, get_vereinsname_lang
from intern.mail import send_config_mail
from intern.mitgliedschaft import antragslink_gilt, ist_mitglied
from intern.models import User
from intern.views.auth import make_antrag_bestand_token


class Command(BaseCommand):
    help = (
        "Schickt einem bestehenden Konto ohne Zugang und ohne Tag „Mitglied“ den Link zum "
        "Mitgliedsantrag (Mailtext MAIL_EINLADUNG). Das Formular ist mit den Kontodaten "
        "vorausgefüllt; Benutzername und Passwort bleiben. Das Konto bleibt inaktiv, bis "
        "der Vorstand die Mitgliedschaft genehmigt. Gültig MITGLIED_EINLADUNG_TAGE Tage."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            required=True,
            metavar="USERNAME",
            help="Benutzername des Kontos, das den Antrag stellen soll.",
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
            help="Nur URL ausgeben, keine Mail senden.",
        )

    def handle(self, *args, **options):
        base_url = get_base_url(options["base_url"], fallback="http://localhost:8000")
        try:
            user = User.objects.get(username=options["user"])
        except User.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Benutzer '{options['user']}' nicht gefunden."))
            return
        if not antragslink_gilt(user.is_active, ist_mitglied(user)):
            self.stderr.write(self.style.ERROR(
                f"'{user.username}' ist schon Mitglied oder hat Zugang — "
                "der Link würde abgewiesen. Nichts gesendet."
            ))
            return

        token = make_antrag_bestand_token(user.pk)
        link = f"{base_url.rstrip('/')}/intern/beitritt/konto/{token}/"
        if options["print_url"]:
            self.stdout.write(link)
            return
        if not user.email:
            self.stderr.write(self.style.ERROR(
                f"'{user.username}' hat keine E-Mail-Adresse — mit --print-url ausgeben."
            ))
            return
        try:
            send_config_mail(
                f"Einladung zu {get_vereinsname_lang()}",
                user.email,
                "MAIL_EINLADUNG",
                link=link,
            )
            self.stdout.write(self.style.SUCCESS(f"OK   {user.username} <{user.email}>"))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"ERR  {user.username}: {exc}"))
