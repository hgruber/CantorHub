from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from filer.models import File

from intern import dateiablage, folders, liedablage
from intern.models import Lied, LiedDatei, User
from intern.verwendung import wiki_verwendungen

# Alter Lied-Feldname → Rollenschlüssel, in Anzeigereihenfolge.
FELDER = (
    ("original", "original"),
    ("aufnahme", "aufnahme"),
    ("notenblatt", "pdf"),
    ("notensatz", "noten"),
)


class Command(BaseCommand):
    help = (
        "Zieht den Repertoire-Bestand in einen Ordner je Lied um: legt "
        "Backstage/Repertoire/<Titel>/ an, legt jede der vier Dateien unter "
        "<Titel> – <Rolle>.<ext> hinein und schreibt die Rollenzeile. Die alten "
        "Lied-Felder bleiben unangetastet. Erst mit --dry-run ansehen; ein "
        "zweiter Lauf tut nichts doppelt. Dateien, die an mehreren Liedern "
        "hängen, werden kopiert; Dateien mit Wiki-Link ziehen mit, behalten "
        "aber ihren Namen, damit der Link weiter auflöst."
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

        # Wer eine Datei an welchem Lied in welcher Rolle trägt — eine Abfrage
        # statt einer je Datei, und die Grundlage für „geteilt".
        referenzen = {}
        for lied_id, original, aufnahme, pdf, noten in Lied.objects.values_list(
            "pk", "original_id", "aufnahme_id", "pdf_id", "noten_id"
        ):
            for rolle, fk in (
                ("original", original),
                ("aufnahme", aufnahme),
                ("notenblatt", pdf),
                ("notensatz", noten),
            ):
                if fk:
                    referenzen.setdefault(fk, []).append((lied_id, rolle))

        dateien = File.objects.in_bulk(referenzen)
        # Wiki-Links adressieren die Datei über ihren Namen; ein Umbenennen
        # bräche sie. Solche Dateien ziehen mit, behalten aber ihren Namen.
        wiki = wiki_verwendungen(
            {f.original_filename or f.name for f in dateien.values()}
        )

        lieder = zeilen = schon = behalten = offen_gesamt = 0
        offen = []
        belegte = {}

        for lied in Lied.objects.only(
            "pk", "titel", "ordner_id", "original_id", "aufnahme_id", "pdf_id", "noten_id"
        ):
            rollen = [
                (rolle, fk)
                for rolle, fk in (
                    ("original", lied.original_id),
                    ("aufnahme", lied.aufnahme_id),
                    ("notenblatt", lied.pdf_id),
                    ("notensatz", lied.noten_id),
                )
                if fk
            ]
            if not rollen:
                continue
            lieder += 1

            if trocken:
                if lied.ordner_id is None:
                    eltern = folders.musik()
                    name = liedablage.freier_name_in(
                        belegte.setdefault(eltern, set()),
                        liedablage.ordnername(lied.titel),
                    )
                    belegte[eltern].add(name)
            else:
                ordner_id = liedablage.ordner_fuer(lied)

            for rolle, fk in rollen:
                if LiedDatei.objects.filter(lied=lied, rolle=rolle).exists():
                    schon += 1
                    continue
                f = dateien.get(fk)
                if f is None:
                    offen.append(f"{lied.titel}: Datei {fk} fehlt")
                    offen_gesamt += 1
                    continue
                # Der Link nennt den Dateinamen: Die Datei zieht um, der Name
                # bleibt, und [[Datei:…]] löst weiter auf.
                name_behalten = (f.original_filename or f.name) in wiki
                name = (
                    f.original_filename or f.name
                    if name_behalten
                    else liedablage.dateiname(lied.titel, rolle, liedablage.endung_von(f))
                )
                if name_behalten:
                    behalten += 1
                geteilt = len(referenzen[fk]) > 1

                if trocken:
                    self.stdout.write(
                        f"{praefix}{lied.titel}: {rolle} → {name}"
                        + (" (Name behalten, Wiki-Link)" if name_behalten else "")
                        + (" (Kopie, an mehreren Liedern)" if geteilt else "")
                    )
                    zeilen += 1
                    continue

                if geteilt:
                    akteur = User.objects.filter(is_superuser=True).order_by("pk").first()
                    if akteur is None:
                        offen.append(
                            f"{lied.titel} ({rolle}): geteilte Datei, kein Superuser als Akteur"
                        )
                        offen_gesamt += 1
                        continue
                    # Jedes Lied bekommt eine eigene Datei; der Name folgt nur
                    # einem Titel, deshalb wird kopiert statt verschoben.
                    with f.file.open("rb") as quelle:
                        inhalt = ContentFile(quelle.read(), name=name)
                    zeile, status, _ = dateiablage.hochladen(
                        inhalt, ordner_id, name, akteur
                    )
                    LiedDatei.objects.create(lied=lied, rolle=rolle, datei=zeile)
                else:
                    liedablage.ablegen(lied, rolle, f, name=name)
                zeilen += 1
                self.stdout.write(f"{lied.titel}: {rolle} → {name}")

        self.stdout.write(
            f"{praefix}{lieder} Lieder mit Dateien, {zeilen} Rollen "
            f"eingetragen{'' if trocken else ' oder kopiert'}, {behalten} Namen "
            f"behalten (Wiki-Link), {schon} schon vorhanden, {offen_gesamt} offen."
        )
        for eintrag in offen:
            self.stderr.write(f"offen: {eintrag}")
