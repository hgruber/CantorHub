"""Misst, wie lange die wichtigsten Portalseiten brauchen — gegen eine Kopie der Datenbank.

Der Ablauf ist der, mit dem die Optimierungen im September 2026 gemessen wurden:
Datenbank kopieren, mit dem Test-Client anmelden, jede Seite einmal warmlaufen
lassen und dann mehrfach abrufen, Median und Abfragezahl ausgeben.

Die Kopie ist der Kern: gemessen wird mit echten Daten, ohne dass ein Lauf die
Datenbank des Betriebs anfasst — jede Anfrage schreibt schließlich mindestens die
Sitzung zurück.
"""

import shutil
import statistics
import tempfile
import time
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.test import Client
from django.test.utils import CaptureQueriesContext

# Die Seiten, die im Alltag zählen. Platzhalter in geschweiften Klammern füllt
# `_ziele` aus der Datenbank — eine fest verdrahtete Id wäre nach dem nächsten
# Import falsch.
SEITEN = [
    ("Aktuell", "/intern/artikel/Aktuell/"),
    ("Artikelliste", "/intern/artikel/"),
    ("Terminliste", "/intern/termin/"),
    ("Kalender", "/intern/kalender/"),
    ("Termin", "/intern/termin/{termin}/"),
    ("Mitgliederliste", "/intern/mitglied/"),
    ("Mitglied", "/intern/mitglied/{mitglied}/"),
    ("Titelliste", "/intern/titel/"),
    ("Titel", "/intern/titel/{lied}/"),
    ("Forenliste", "/intern/forum/"),
    ("Forum", "/intern/forum/{forum}/"),
    ("Forum-Poll", "/intern/forum/{forum}/get/"),
    ("Benachrichtigungen", "/intern/notify/"),
    ("Ordner", "/intern/ordner/{ordner}/"),
    ("Galerie", "/intern/gallerie/{bildordner}/"),
    ("Karte", "/intern/karte/"),
    ("Ortliste", "/intern/ort/"),
    ("Homepage", "/"),
]


class Command(BaseCommand):
    help = (
        "Misst die Antwortzeit und die Zahl der Datenbankabfragen der wichtigsten "
        "Seiten. Läuft gegen eine Kopie der Datenbank, die danach wieder "
        "verschwindet — der Betrieb bleibt unberührt. Nur für SQLite; mit MySQL "
        "fehlt der Kopierweg."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--nutzer", metavar="NAME",
            help="Anmeldename, unter dem gemessen wird (Standard: ein Mitglied "
                 "ohne Verwaltungsrechte, sonst der erste aktive).",
        )
        parser.add_argument(
            "--laeufe", type=int, default=5, metavar="N",
            help="Abrufe je Seite nach dem Warmlauf (Standard: 5).",
        )
        parser.add_argument(
            "--seite", metavar="TEXT",
            help="Nur Seiten messen, deren Name diesen Text enthält.",
        )

    def handle(self, *args, **optionen):
        kopie, aufraeumen = self._kopie_anlegen()
        try:
            self._messen(kopie, optionen)
        finally:
            aufraeumen()

    # --- Datenbank ----------------------------------------------------------------

    def _kopie_anlegen(self):
        """Legt eine Kopie der SQLite-Datei an und schaltet die Verbindung darauf um."""
        einstellungen = settings.DATABASES["default"]
        if "sqlite" not in einstellungen["ENGINE"]:
            raise CommandError(
                "Diese Messung braucht SQLite. Bei MySQL zuerst einen Abzug in eine "
                "SQLite-Datei ziehen oder gegen eine Testinstanz messen."
            )
        quelle = Path(einstellungen["NAME"])
        if not quelle.exists():
            raise CommandError(f"Datenbank {quelle} nicht gefunden.")

        verzeichnis = Path(tempfile.mkdtemp(prefix="seitenmessung-"))
        ziel = verzeichnis / quelle.name
        shutil.copy2(quelle, ziel)
        self.stdout.write(f"Kopie: {ziel} ({ziel.stat().st_size // 1024} KB)")

        verbindung = connections["default"]
        verbindung.close()
        verbindung.settings_dict["NAME"] = str(ziel)

        def aufraeumen():
            verbindung.close()
            verbindung.settings_dict["NAME"] = str(quelle)
            shutil.rmtree(verzeichnis, ignore_errors=True)

        return ziel, aufraeumen

    # --- Messung ------------------------------------------------------------------

    def _nutzer(self, name):
        from intern.models import User

        if name:
            nutzer = User.objects.filter(username=name).first()
            if nutzer is None:
                raise CommandError(f"Kein Mitglied mit dem Namen „{name}“.")
            return nutzer
        # Ein gewöhnliches Mitglied ist der Regelfall; Verwalter sehen mehr Spalten
        # und messen deshalb etwas anderes.
        nutzer = (
            User.objects.filter(is_active=True, is_superuser=False, is_staff=False)
            .order_by("id").first()
            or User.objects.filter(is_active=True).order_by("id").first()
        )
        if nutzer is None:
            raise CommandError("Keine Mitglieder in der Datenbank.")
        return nutzer

    def _ziele(self):
        """Ids für die Platzhalter in `SEITEN`, aus den vorhandenen Daten."""
        from filer.models import File, Folder
        from intern.models import Forum, Lied, Termin

        bildordner = (
            File.objects.filter(mime_type__startswith="image/")
            .values_list("folder_id", flat=True).first()
        )
        return {
            "termin": Termin.objects.order_by("-datum").values_list("id", flat=True).first(),
            "mitglied": None,   # wird in handle() auf den messenden Nutzer gesetzt
            "lied": Lied.objects.values_list("id", flat=True).first(),
            "forum": Forum.objects.values_list("id", flat=True).first(),
            "ordner": Folder.objects.values_list("id", flat=True).first(),
            "bildordner": bildordner,
        }

    def _messen(self, kopie, optionen):
        nutzer = self._nutzer(optionen.get("nutzer"))
        ziele = self._ziele()
        ziele["mitglied"] = nutzer.pk
        laeufe = max(1, optionen["laeufe"])
        filter_text = (optionen.get("seite") or "").lower()

        client = Client()
        client.force_login(nutzer)
        self.stdout.write(
            f"Mitglied: {nutzer.username} "
            f"({'Verwaltung' if nutzer.is_superuser or nutzer.is_staff else 'ohne Sonderrechte'}), "
            f"{laeufe} Läufe je Seite\n"
        )
        self.stdout.write(f"{'Seite':22}{'Status':>7}{'Median':>9}{'Min':>8}{'Abfragen':>10}   Auffällig")

        verbindung = connections["default"]
        for name, muster in SEITEN:
            if filter_text and filter_text not in name.lower():
                continue
            try:
                pfad = muster.format(**ziele)
            except KeyError:
                continue
            if "None" in pfad:
                self.stdout.write(f"{name:22}{'—':>7}   (keine Daten dafür)")
                continue

            kopf = {"HTTP_HX_REQUEST": "true"} if pfad.endswith("/get/") else {}
            client.get(pfad, **kopf)          # Warmlauf: Vorlagen und Verbindungen stehen
            zeiten = []
            for _ in range(laeufe):
                with CaptureQueriesContext(verbindung) as abfragen:
                    beginn = time.perf_counter()
                    antwort = client.get(pfad, **kopf)
                    if hasattr(antwort, "streaming_content"):
                        b"".join(antwort.streaming_content)
                    zeiten.append((time.perf_counter() - beginn) * 1000)
            self.stdout.write(
                f"{name:22}{antwort.status_code:>7}"
                f"{statistics.median(zeiten):>8.1f}ms{min(zeiten):>7.1f}ms"
                f"{len(abfragen.captured_queries):>10}   "
                f"{self._wiederholungen(abfragen.captured_queries)}"
            )

    @staticmethod
    def _wiederholungen(abfragen):
        """Nennt die häufigste Abfrage, wenn sie mehr als dreimal vorkommt.

        Genau so fallen die Muster auf, bei denen eine Seite je Zeile eine eigene
        Abfrage stellt — der Grund für die meisten langsamen Seiten.
        """
        import re

        muster = Counter(
            re.sub(r"\b\d+\b", "?", eintrag["sql"])[:70] for eintrag in abfragen
        )
        if not muster:
            return ""
        sql, anzahl = muster.most_common(1)[0]
        return f"{anzahl}× {sql}" if anzahl > 3 else ""
