from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from intern import hilfe
from intern.models import User


class Command(BaseCommand):
    help = (
        "Legt die mitgelieferten Hilfe-Artikel (Hilfe, Hilfe:…) samt Bildern an, "
        "soweit es sie noch nicht gibt. Vorhandene Artikel bleiben unverändert — "
        "für bestehende Installationen; eine neue bekommt sie bei der Ersteinrichtung."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--autor",
            metavar="BENUTZERNAME",
            help="Wer als Autor eingetragen wird (Standard: der älteste Administrator).",
        )

    def handle(self, *args, **options):
        if options["autor"]:
            autor = User.objects.filter(username=options["autor"]).first()
            if autor is None:
                raise CommandError(f"Kein Benutzer {options['autor']!r}.")
        else:
            autor = User.objects.filter(is_superuser=True).order_by("pk").first()
            if autor is None:
                raise CommandError("Kein Administrator vorhanden — erst die Ersteinrichtung abschließen.")

        neu = hilfe.anlegen(autor, timezone.now())
        for name in neu:
            self.stdout.write(f"angelegt: {name}")
        self.stdout.write(self.style.SUCCESS(
            f"{len(neu)} von {len(hilfe.ARTIKEL)} Hilfe-Artikeln neu angelegt."
        ))
