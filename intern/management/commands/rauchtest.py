"""Prüft die wichtigsten Portalseiten gegen echte Daten — ohne Testdatenbank.

`seitenmessung` beantwortet die Frage „wie schnell?“, dieser Befehl die Frage
„läuft es überhaupt?“. Er ruft dieselbe Seitenliste ab und wertet jede Antwort
als Fehler, die eine Ausnahme auslöst oder mit 4xx/5xx endet.

Gedacht ist er für einen Abzug der Produktion: Dort stehen die Altdaten, an
denen Vorlagen, Filter und Markup scheitern — genau das sieht die
Datenbank-freie Testsuite nicht. Der Befehl läuft deshalb nicht in
`manage.py test intern` mit, sondern getrennt gegen die Datenbank, die
`DATABASE_URL` gerade nennt; der Exitcode taugt für die Automatisierung.
"""

from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from intern.management.commands.seitenmessung import SEITEN, mitglied, ziele


class Command(BaseCommand):
    help = (
        "Ruft die wichtigsten Portalseiten ab und meldet jede, die eine Ausnahme "
        "auslöst oder mit 4xx/5xx antwortet. Für einen Abzug der Produktion; der "
        "Exitcode ist ungleich 0, sobald eine Seite scheitert."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--nutzer", metavar="NAME",
            help="Anmeldename, unter dem geprüft wird (Standard: ein Mitglied "
                 "ohne Verwaltungsrechte, sonst der erste aktive).",
        )
        parser.add_argument(
            "--seite", metavar="TEXT",
            help="Nur Seiten prüfen, deren Name diesen Text enthält.",
        )

    def handle(self, *args, **optionen):
        person = mitglied(optionen.get("nutzer"))
        platzhalter = ziele()
        platzhalter["mitglied"] = person.pk
        filter_text = (optionen.get("seite") or "").lower()

        # Wie bei `seitenmessung`: der Test-Client meldet sich als „testserver“,
        # ein Name, den nur `setup_test_environment()` in ALLOWED_HOSTS einträgt.
        client = Client(SERVER_NAME="localhost")
        client.force_login(person)

        self.stdout.write(
            f"Mitglied: {person.username} "
            f"({'Verwaltung' if person.is_superuser or person.is_staff else 'ohne Sonderrechte'})\n"
        )
        self.stdout.write(f"{'Seite':22}{'Status':>7}  Pfad")

        geprueft = 0
        fehler = []
        for name, muster in SEITEN:
            if filter_text and filter_text not in name.lower():
                continue
            pfad = muster.format(**platzhalter)
            if "None" in pfad:
                self.stdout.write(f"{name:22}{'—':>7}  (keine Daten dafür)")
                continue

            kopf = {"HTTP_HX_REQUEST": "true"} if pfad.endswith("/get/") else {}
            geprueft += 1
            try:
                antwort = client.get(pfad, **kopf)
                if hasattr(antwort, "streaming_content"):
                    b"".join(antwort.streaming_content)
            except Exception as ausnahme:
                fehler.append((name, pfad, f"{type(ausnahme).__name__}: {ausnahme}"))
                self.stdout.write(f"{name:22}{'FEHLER':>7}  {pfad}")
                continue
            if antwort.status_code >= 400:
                fehler.append((name, pfad, f"Status {antwort.status_code}"))
            self.stdout.write(f"{name:22}{antwort.status_code:>7}  {pfad}")

        if not geprueft:
            raise CommandError(
                "Keine Seite geprüft — die Datenbank enthält keine passenden Daten."
            )
        if fehler:
            for name, pfad, grund in fehler:
                self.stderr.write(f"{name} ({pfad}): {grund}")
            raise CommandError(f"{len(fehler)} von {geprueft} Seiten scheitern.")
        self.stdout.write(f"\n{geprueft} Seiten ohne Fehler.")
