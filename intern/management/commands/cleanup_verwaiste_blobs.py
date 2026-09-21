import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from filer.models import File
from filer.settings import (
    FILER_PUBLICMEDIA_THUMBNAIL_OPTIONS,
    FILER_STORAGES,
)

from intern.blob_aufraeumen import (
    BLOB_PRAEFIX,
    THUMBNAIL_PRAEFIX,
    verwaiste_pfade,
)
from intern.models import DateiVersion

# Wie lange eine Datei mindestens liegen muss, bevor sie als Waise gilt. Ein
# laufender Upload hat seinen Blob schon geschrieben, wenn seine Zeile noch
# nicht committet ist; ohne diese Schonfrist löscht ein gleichzeitig laufendes
# Aufräumen ihn unter der Anfrage weg.
DEFAULT_MIN_ALTER_MINUTEN = 60


def _praefixe():
    """Die beiden Präfixe aus filers Storage-Konfiguration.

    Nicht fest verdrahten: ``FILER_PUBLICMEDIA_PREFIX`` ist einstellbar, und
    ein Kommando, das mit dem falschen Präfix sucht, findet entweder nichts
    oder hält den gesamten Bestand für verwaist.
    """
    blob = FILER_STORAGES["public"]["main"].get("UPLOAD_TO_PREFIX", BLOB_PRAEFIX)
    thumb = FILER_PUBLICMEDIA_THUMBNAIL_OPTIONS.get("base_dir", THUMBNAIL_PRAEFIX)
    return blob, thumb


def _bekannte_pfade():
    """Jeder Blob-Pfad, den die Datenbank nennt.

    Zwei Quellen, und beide müssen hinein: ``File.file`` für die lebenden
    Dateien, ``DateiVersion`` für die alten Fassungen, deren Blobs bewusst
    ohne File-Zeile liegen. ``aktuell`` zeigt zwar auf eine Datei, die auch in
    der ersten Menge steht — aber nur, solange die Kette konsistent ist, und
    dieses Kommando ist der falsche Ort, sich darauf zu verlassen.
    """
    pfade = set(File.objects.values_list("file", flat=True))
    pfade.update(DateiVersion.objects.values_list("pfad", flat=True))
    pfade.update(DateiVersion.objects.values_list("aktuell", flat=True))
    pfade.discard(None)
    pfade.discard("")
    return pfade


def _gefundene_pfade(wurzel, praefixe, hoechstens_mtime):
    """Alle Dateien unter den Präfixen, die alt genug sind, als relative Pfade."""
    for praefix in praefixe:
        basis = os.path.join(wurzel, praefix)
        for ordner, _, dateien in os.walk(basis):
            for name in dateien:
                voll = os.path.join(ordner, name)
                try:
                    if os.stat(voll).st_mtime > hoechstens_mtime:
                        continue
                except OSError:
                    continue
                yield os.path.relpath(voll, wurzel).replace(os.sep, "/")


def _leere_ordner_entfernen(ordner, grenze):
    """Leere Verzeichnisse nach oben abräumen, aber nicht über `grenze` hinaus.

    ``os.removedirs`` liefe weiter, bis ein Verzeichnis nicht leer ist, und
    nähme bei einem vollständig geleerten Bestand auch ``filer_public`` und
    ``media`` selbst mit. Die legt danach nur ``start.sh`` wieder an.
    """
    ordner = os.path.abspath(ordner)
    grenze = os.path.abspath(grenze)
    while ordner.startswith(grenze + os.sep):
        try:
            os.rmdir(ordner)
        except OSError:
            return
        ordner = os.path.dirname(ordner)


def _lesbare_groesse(bytes_):
    for einheit in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024 or einheit == "GB":
            return f"{bytes_:.1f} {einheit}"
        bytes_ /= 1024


class Command(BaseCommand):
    help = (
        "Meldet Blobs unter MEDIA_ROOT, die keine Datenbankzeile mehr haben, "
        "und löscht sie auf Wunsch. Hintergrund sind die Migrationsläufe: "
        "MIGRATE=1 verwirft die Datenbank, filer vergibt beim nächsten Import "
        "neue UUID-Pfade, und der alte Bestand bleibt unreferenziert liegen. "
        "Ohne --loeschen wird nur berichtet. Ersetzt NICHT 'filer_check "
        "--delete-orphans' — das Kommando ist hier verboten, weil es die "
        "DateiVersion-Blobs mitnähme; dieses hier kennt sie."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--loeschen",
            action="store_true",
            help="Die gefundenen Waisen wirklich löschen. Ohne dieses Flag "
            "passiert nichts — die Blobs sind danach unwiederbringlich weg.",
        )
        parser.add_argument(
            "--min-alter",
            type=int,
            default=DEFAULT_MIN_ALTER_MINUTEN,
            metavar="MINUTEN",
            help="Dateien, die jünger sind, bleiben unangetastet (Standard: "
            "60). Schützt einen Upload, dessen Zeile noch nicht committet ist.",
        )
        parser.add_argument(
            "--liste",
            action="store_true",
            help="Jeden gefundenen Pfad einzeln ausgeben.",
        )

    def handle(self, *args, **options):
        wurzel = str(settings.MEDIA_ROOT)
        blob_praefix, thumbnail_praefix = _praefixe()
        grenze = time.time() - options["min_alter"] * 60

        bekannte = _bekannte_pfade()
        gefundene = _gefundene_pfade(
            wurzel, (blob_praefix, thumbnail_praefix), grenze
        )
        waisen = verwaiste_pfade(
            gefundene, bekannte, blob_praefix, thumbnail_praefix
        )

        if not waisen:
            self.stdout.write(
                f"Keine verwaisten Blobs ({len(bekannte)} Pfade in der Datenbank)."
            )
            return

        groesse = 0
        for pfad in waisen:
            try:
                groesse += os.path.getsize(os.path.join(wurzel, pfad))
            except OSError:
                pass

        if options["liste"]:
            for pfad in waisen:
                self.stdout.write(f"  {pfad}")

        if not options["loeschen"]:
            self.stdout.write(
                f"{len(waisen)} verwaiste Dateien, {_lesbare_groesse(groesse)}. "
                f"Nichts gelöscht — mit --loeschen wiederholen."
            )
            return

        geloescht = 0
        for pfad in waisen:
            voll = os.path.join(wurzel, pfad)
            try:
                os.remove(voll)
                geloescht += 1
            except OSError:
                self.stderr.write(f"{pfad} nicht löschbar.")
                continue
            # Die UUID-Verzeichnisse tragen je eine Datei; bleiben sie stehen,
            # sammelt das Volume statt der Blobs eben leere Ordner an. Grenze
            # ist das Präfix-Verzeichnis, also der erste Bestandteil des
            # relativen Pfads.
            _leere_ordner_entfernen(
                os.path.dirname(voll), os.path.join(wurzel, pfad.split("/")[0])
            )
        self.stdout.write(
            f"{geloescht} verwaiste Dateien gelöscht, "
            f"{_lesbare_groesse(groesse)} frei."
        )
