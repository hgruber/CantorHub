"""Der einzige Weg in einen Lied-Ordner.

Ein Lied hält seine Dateien in einem eigenen filer-Ordner unter
``Backstage/Repertoire/<Titel>/``. Wie ``dateiablage.py`` für Ordner ist
dieses Modul die einzige Stelle, die dort ablegt; welche Rolle eine Datei hat,
steht in ``intern/liedrollen.py``.
"""

import os

from filer.models import File, Folder

from . import dateiablage, folders, liedrollen
from .models import Lied, LiedDatei

# Bis Migration 0006 die vier Spalten entfernt: Rolle → altes Lied-Feld. Der
# Rückfall liest Dateien, die im Fenster zwischen Bestandsumzug und
# Umschaltung noch über den alten Upload-Wege dazukamen.
ALT_ROLLEN = (
    ("original", "original"),
    ("aufnahme", "aufnahme"),
    ("notenblatt", "pdf"),
    ("notensatz", "noten"),
)

# Rolle → altes Feld, für den Dual-Write bis Migration 0006. `text` hat keins.
ROLLEN_JE_FELD = {rolle: feld for rolle, feld in ALT_ROLLEN}
FELD_ROLLE = {feld: rolle for rolle, feld in ALT_ROLLEN}


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


def rollen_fuer(lieder):
    """{lied_id: {rolle: filer.File}} für eine Liste, ein Queryset oder eine Seite.

    Die Rollenzeile gilt. Fehlt sie, liest der alte FK (``ALT_ROLLEN``) —
    damit bleibt sichtbar, was im Fenster zwischen Bestandsumzug und
    Umschaltung noch über den alten Weg dazukam. Die FKs werden als IDs
    gelesen und nur die tatsächlich fehlenden Zeilen nachgeladen; das kostet
    keine ``File``-Objekte für die ganze Seite.
    """
    lieder = list(lieder)
    ids = [lied.pk for lied in lieder]
    ergebnis = {pk: {} for pk in ids}
    if not ids:
        return ergebnis
    for zeile in LiedDatei.objects.filter(lied_id__in=ids).select_related("datei"):
        ergebnis[zeile.lied_id][zeile.rolle] = zeile.datei

    nachzulesen = []
    for lied_id, original, aufnahme, pdf, noten in Lied.objects.filter(
        pk__in=ids
    ).values_list("pk", "original_id", "aufnahme_id", "pdf_id", "noten_id"):
        for (rolle, _), fk in zip(ALT_ROLLEN, (original, aufnahme, pdf, noten)):
            if fk and rolle not in ergebnis[lied_id]:
                nachzulesen.append((lied_id, rolle, fk))
    if nachzulesen:
        dateien = File.objects.in_bulk({fk for _, _, fk in nachzulesen})
        for lied_id, rolle, fk in nachzulesen:
            datei = dateien.get(fk)
            if datei is not None:
                ergebnis[lied_id][rolle] = datei
    return ergebnis


def rollen_von(lied):
    return rollen_fuer([lied])[lied.pk]


def datei_fuer(lied, rolle):
    """Die Datei einer Rolle, oder ``None``."""
    return rollen_von(lied).get(rolle)


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


def titel_geaendert(lied, neuer_titel):
    """Ordner und Dateinamen dem neuen Titel nachziehen.

    Der Ordnername ist nur Anzeige; die Zuordnung trägt der FK. Ein geteilter
    Blob folgt dabei dem letzten Titel — dieselbe Grenze wie bei jeder
    Umbenennung über ``dateiablage.datei_umbenennen``."""
    if not lied.ordner_id:
        return
    ordner = Folder.objects.filter(pk=lied.ordner_id).first()
    if ordner is not None:
        vorhandene = set(
            Folder.objects.filter(parent_id=ordner.parent_id)
            .exclude(pk=ordner.pk)
            .values_list("name", flat=True)
        )
        name = freier_name_in(vorhandene, ordnername(neuer_titel))
        if ordner.name != name:
            Folder.objects.filter(pk=ordner.pk).update(name=name)
    for zeile in LiedDatei.objects.filter(lied=lied).select_related("datei"):
        neu = dateiname(neuer_titel, zeile.rolle, endung_von(zeile.datei))
        if (zeile.datei.original_filename or zeile.datei.name) != neu:
            dateiablage.datei_umbenennen(zeile.datei, neu)
