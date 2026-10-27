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
    # Der Besitzer ist keine Rechtsfrage (das entscheidet `FolderPermission`),
    # aber er steht im Dateibrowser und wird beim Austritt gelesen — der
    # Lied-Ordner erbt ihn deshalb vom Repertoire-Ordner.
    eltern_owner = Folder.objects.filter(pk=eltern).values_list("owner_id", flat=True).first()
    vorhandene = set(
        Folder.objects.filter(parent_id=eltern).values_list("name", flat=True)
    )
    ordner = Folder.objects.create(
        name=freier_name_in(vorhandene, ordnername(lied.titel)),
        parent_id=eltern,
        owner_id=eltern_owner,
    )
    Lied.objects.filter(pk=lied.pk).update(ordner=ordner)
    lied.ordner_id = ordner.pk
    return ordner.pk


def rollen_fuer(lieder):
    """{lied_id: {rolle: filer.File}} für eine Liste, ein Queryset oder eine Seite.

    Eine Abfrage für die ganze Seite, samt Dateien: eine Liste braucht die
    Rollen aller ihrer Zeilen, nicht eine Abfrage je Zeile."""
    lieder = list(lieder)
    ids = [lied.pk for lied in lieder]
    ergebnis = {pk: {} for pk in ids}
    if not ids:
        return ergebnis
    for zeile in LiedDatei.objects.filter(lied_id__in=ids).select_related("datei"):
        ergebnis[zeile.lied_id][zeile.rolle] = zeile.datei
    return ergebnis


def rollen_von(lied):
    return rollen_fuer([lied])[lied.pk]


def datei_fuer(lied, rolle):
    """Die Datei einer Rolle, oder ``None``."""
    return rollen_von(lied).get(rolle)


def dateien_im_ordner(lied):
    """Alle Dateien des Lied-Ordners, ohne Unterordner — auch die ohne Rolle."""
    if not lied.ordner_id:
        return []
    return list(
        File.objects.filter(folder_id=lied.ordner_id).order_by("original_filename", "name")
    )


def rolle_setzen(lied, rolle, datei, nutzer=None):
    """Die Rollenzeile auf `datei` setzen — für Dateien, die schon im
    Lied-Ordner liegen. `nutzer` landet im Änderungsprotokoll.

    Je Lied hängt eine Rolle an einer Datei, und eine Datei trägt höchstens
    eine Rolle: eine andere Rolle derselben Datei wird dabei frei."""
    _zeilen_loeschen(
        LiedDatei.objects.filter(lied=lied, datei=datei).exclude(rolle=rolle), nutzer
    )
    zeile = LiedDatei.objects.filter(lied=lied, rolle=rolle).first()
    if zeile is None:
        zeile = LiedDatei(lied=lied, rolle=rolle)
    elif zeile.datei_id == datei.pk:
        return  # schon eingetragen — kein Schreibvorgang, kein Protokolleintrag
    zeile.datei = datei
    zeile._audit_user = nutzer
    zeile.save()


def rolle_entfernen(lied, datei, nutzer=None):
    """Die Rolle dieser Datei lösen."""
    _zeilen_loeschen(LiedDatei.objects.filter(lied=lied, datei=datei), nutzer)


def _zeilen_loeschen(zeilen, nutzer):
    """Rollenzeilen einzeln löschen — protokolliert, weil ein Löschen über das
    Queryset am Änderungsprotokoll vorbeiginge."""
    from .signals import _log_change

    for zeile in zeilen:
        zeile._audit_user = nutzer
        _log_change(zeile, nutzer, "delete")
        zeile.delete()


def ablegen(lied, rolle, datei, name=None, nutzer=None):
    """`datei` in den Lied-Ordner legen und als `rolle` eintragen.

    Der Name ist reine Kosmetik; liegt dort schon eine Datei dieses Namens,
    wird die neue ihre vordere Fassung (siehe ``dateiablage.systemablage``)."""
    ordner_id = ordner_fuer(lied)
    name = name or dateiname(lied.titel, rolle, endung_von(datei))
    zeile = dateiablage.systemablage(datei, ordner_id, name)
    rolle_setzen(lied, rolle, zeile, nutzer)
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
