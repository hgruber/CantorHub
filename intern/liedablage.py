"""Der einzige Weg in einen Lied-Ordner.

Ein Lied hält seine Dateien in einem eigenen filer-Ordner unter
``Backstage/Repertoire/<Titel>/``. Wie ``dateiablage.py`` für Ordner ist
dieses Modul die einzige Stelle, die dort ablegt; welche Rolle eine Datei hat,
steht in ``intern/liedrollen.py``.
"""

import os

from filer.models import Folder

from . import dateiablage, folders, liedrollen
from .models import Lied, LiedDatei


def ordnername(titel):
    """Der Titel als Ordnername — entschärft, was ein Ordner nicht tragen kann."""
    name = (titel or "").strip().replace("/", "-").replace("\\", "-")
    name = name[:255].strip()
    return "Ohne Titel" if name in ("", ".", "..") else name


def freier_name_in(vorhandene, base):
    """`base`, sonst `base-1`, `base-2` … — wie `_unique_folder_name` in
    ``views/folders.py``, aber auf einer übergebenen Namensmenge und damit
    ohne Datenbank prüfbar."""
    if base not in vorhandene:
        return base
    n = 1
    while f"{base}-{n}" in vorhandene:
        n += 1
    return f"{base}-{n}"


def endung_von(datei):
    return os.path.splitext(datei.original_filename or datei.name or "")[1].lower()


def dateiname(titel, rolle, endung):
    """`<Titel> – <Rolle>.<ext>` — Anzeigename, keine Wahrheit."""
    return f"{ordnername(titel)} – {liedrollen.label(rolle)}{endung}"


def ordner_fuer(lied):
    """Die ID des Lied-Ordners; legt ihn beim ersten Bedarf an.

    Ist der Ordner schon da, gewinnt der FK — nicht der Ordnername, den ein
    Mitglied im Dateibrowser umbenannt haben kann."""
    if lied.ordner_id:
        return lied.ordner_id
    eltern = folders.musik()
    if eltern is None:
        raise ValueError("Backstage/Repertoire fehlt — zuerst die Einrichtung laufen lassen")
    vorhandene = set(
        Folder.objects.filter(parent_id=eltern).values_list("name", flat=True)
    )
    ordner = Folder.objects.create(
        name=freier_name_in(vorhandene, ordnername(lied.titel)), parent_id=eltern
    )
    Lied.objects.filter(pk=lied.pk).update(ordner=ordner)
    lied.ordner_id = ordner.pk
    return ordner.pk


def ablegen(lied, rolle, datei, name=None):
    """`datei` in den Lied-Ordner legen und als `rolle` eintragen.

    Der Name ist reine Kosmetik; liegt dort schon eine Datei dieses Namens,
    wird die neue ihre vordere Fassung (siehe ``dateiablage.systemablage``)."""
    ordner_id = ordner_fuer(lied)
    name = name or dateiname(lied.titel, rolle, endung_von(datei))
    zeile = dateiablage.systemablage(datei, ordner_id, name)
    LiedDatei.objects.update_or_create(
        lied=lied, rolle=rolle, defaults={"datei": zeile}
    )
    return zeile
