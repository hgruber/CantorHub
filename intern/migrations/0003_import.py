"""Leerer Platzhalter des einmaligen Altdaten-Imports.

Hier stand bis Oktober 2026 der Import aus dem PHP-Altportal. Er ist auf der
einzigen Installation, die ihn brauchte, gelaufen und dort verbucht; er wird nie
wieder benötigt. Die Datei bleibt nur, weil die Kette an ihr hängt
(``0004_termin_dateien`` und jede Installation, die sie verbucht hat).

Eine neue Installation spielt sie leer durch; Gruppen, Standardordner und das
erste Konto legt die Ersteinrichtung an (``intern/einrichtung.py``). Nicht
wiederbeleben, nicht füllen.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("intern", "0002_add_filer"),
    ]

    operations = []
