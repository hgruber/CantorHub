"""Spielt eine bereite Wiederherstellung ein (``intern/wiederherstellung.py``).

Ruft ``start.sh`` bei jedem Start vor ``migrate`` auf; ohne Auftrag tut es
nichts. Ein Fehler beendet es nicht mit einem Fehlercode — der Container soll
starten und die Seite der Ersteinrichtung den Grund zeigen.
"""

from django.core.management.base import BaseCommand

from intern.wiederherstellung import einspielen


class Command(BaseCommand):
    help = "Spielt eine über die Ersteinrichtung vorbereitete Wiederherstellung ein."

    def handle(self, *args, **options):
        ergebnis = einspielen()
        if ergebnis:
            self.stdout.write(self.style.SUCCESS("Wiederherstellung eingespielt."))
        elif ergebnis is False:
            self.stderr.write(self.style.WARNING(
                "Wiederherstellung fehlgeschlagen — der Grund steht auf /einrichtung/."
            ))
