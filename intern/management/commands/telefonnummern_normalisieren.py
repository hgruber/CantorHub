from django.core.management.base import BaseCommand

from intern import telefon
from intern.app_settings import get_config
from intern.models import User


class Command(BaseCommand):
    help = (
        "Schreibt die gespeicherten Telefon- und Faxnummern in die internationale "
        "Form („+49 69 1234567“). Die Landesvorwahl kommt aus der Konfiguration "
        "(TELEFON_LANDESVORWAHL). Was sich nicht als Nummer lesen lässt, bleibt "
        "unverändert und wird aufgelistet. Erst mit --dry-run ansehen: der Lauf "
        "schreibt keine Zeile ins Änderungsprotokoll, die Ausgabe ist der Beleg. "
        "Adressbücher auf den Telefonen laden die geänderten Karten danach einmal neu."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Nur anzeigen, was sich ändern würde; nichts schreiben.",
        )

    def handle(self, *args, **options):
        trocken = options["dry_run"]
        praefix = "[dry-run] " if trocken else ""
        vorwahl = get_config("TELEFON_LANDESVORWAHL") or telefon.LANDESVORWAHL_STANDARD

        mitglieder = angepasst = unveraendert = unlesbar = 0
        for user in User.objects.all().only("pk", "username", *telefon.FELDER):
            geaendert = {}
            for feld in telefon.FELDER:
                alt = getattr(user, feld) or ""
                if not alt.strip():
                    continue
                neu = telefon.normalisiere(alt, vorwahl)
                if neu is None:
                    unlesbar += 1
                    self.stderr.write(
                        f"{user.username}.{feld}: „{alt}“ lässt sich nicht umformen "
                        f"— unverändert."
                    )
                elif neu == alt:
                    unveraendert += 1
                else:
                    geaendert[feld] = neu
                    self.stdout.write(f"{praefix}{user.username}.{feld}: {alt} → {neu}")

            if geaendert:
                mitglieder += 1
                angepasst += len(geaendert)
                if not trocken:
                    # Bewusst update() statt save(): der post_save-Handler am User kann
                    # Aktivierungs- und Willkommensmails versenden, und _AUDIT_FIELDS
                    # kennt nur zwei der fünf Nummernfelder — ein Mengenlauf hinterließe
                    # Protokollzeilen ohne Akteur und teils ohne Inhalt.
                    User.objects.filter(pk=user.pk).update(**geaendert)

        self.stdout.write(
            f"{praefix}{mitglieder} Mitglieder, {angepasst} Nummern angepasst, "
            f"{unveraendert} schon im Format, {unlesbar} nicht umformbar."
        )
