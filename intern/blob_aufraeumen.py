"""Welche Dateien unter ``MEDIA_ROOT`` keine Datenbankzeile mehr haben.

filer vergibt jeder Datei einen frischen UUID-Pfad
(``filer.utils.generate_filename.randomized``): ein Import überschreibt nichts,
er legt alles neu daneben. Wirft ein Migrationslauf (``MIGRATE=1``) die
Datenbank weg, ohne ``media/`` mitzunehmen, bleibt der gesamte Bestand des
vorherigen Laufs im Volume liegen — von niemandem mehr referenziert, und von
niemandem mehr auffindbar, weil die Zeilen fehlen, die seine Pfade nannten.

filers eigenes ``filer_check --delete-orphans`` taugt zum Aufräumen nicht: es
hält jeden Blob ohne ``filer.File``-Zeile für einen Waisen, und das ist genau
die Bauform einer alten Dateifassung (siehe ``DateiVersion`` in ``models.py``,
deren Blob bewusst ohne File-Zeile liegenbleibt). Es würde die gesamte
Versionshistorie löschen — daher das Verbot in ``CLAUDE.md``.

Hier steckt nur die Regel, ohne Datenbank und ohne Dateisystem, damit sie
testbar bleibt; die beiden Hälften, die zugreifen, stehen in
``cleanup_verwaiste_blobs``.
"""

import posixpath

# Beide Präfixe stammen aus filers Storage-Konfiguration (``UPLOAD_TO_PREFIX``
# bzw. die ``base_dir`` der Thumbnail-Optionen). Das Kommando liest sie von
# dort und reicht sie durch; die Vorgaben hier sind filers Standardwerte.
BLOB_PRAEFIX = "filer_public"
THUMBNAIL_PRAEFIX = "filer_public_thumbnails"


def _unter(pfad, praefix):
    """Liegt `pfad` unterhalb von `praefix`?

    Der Trenner gehört zum Vergleich: ohne ihn wäre „filer_public_thumbnails/…"
    auch ein Treffer auf „filer_public" — die Thumbnails eines lebenden Blobs
    kämen dann in den Zweig für die Blobs selbst.
    """
    return pfad.startswith(praefix + "/")


def zugeordnetes_verzeichnis(
    pfad, blob_praefix=BLOB_PRAEFIX, thumbnail_praefix=THUMBNAIL_PRAEFIX
):
    """Das Blob-Verzeichnis, über dessen Fortbestand `pfad` mitentscheidet.

    Für einen Blob ist das sein eigenes Verzeichnis. Für ein Thumbnail das
    gespiegelte: easy_thumbnails legt den Quellpfad unter die ``base_dir`` und
    hängt die Geometrie an den Dateinamen,
    ``filer_public_thumbnails/filer_public/de/ad/<uuid>/126.jpg__32x32_q85.jpg``.
    None, wenn der Pfad unter keinem der beiden Präfixe liegt.
    """
    if _unter(pfad, thumbnail_praefix):
        return posixpath.dirname(pfad[len(thumbnail_praefix) + 1:])
    if _unter(pfad, blob_praefix):
        return posixpath.dirname(pfad)
    return None


def verwaiste_pfade(
    gefundene,
    bekannte,
    blob_praefix=BLOB_PRAEFIX,
    thumbnail_praefix=THUMBNAIL_PRAEFIX,
):
    """Die Pfade aus `gefundene`, zu denen die Datenbank nichts mehr weiß.

    `gefundene` sind relative Pfade unterhalb von ``MEDIA_ROOT`` mit
    POSIX-Trennern, `bekannte` die Blob-Pfade, die die Datenbank noch nennt.
    Alles außerhalb der beiden Präfixe bleibt unangetastet: was dort liegt,
    hat filer nicht angelegt, und über dessen Lebensdauer weiß diese Regel
    nichts.

    Entschieden wird über das **Verzeichnis**, nicht über den einzelnen Pfad,
    und das aus zwei Gründen, die beide in der Ablage begründet liegen:

    - Neben einem Blob liegen Dateien, die in keiner Spalte stehen: die
      96×96-Vorschauen der Dateiversionen landen mangels Storage-Konfiguration
      *innerhalb* von ``filer_public/`` statt unter der Thumbnail-``base_dir``
      (siehe „A version blob has no File row" in ``docs/files.md``). Pfadweise
      verglichen wären sie Waisen und fielen bei jedem Lauf weg.
    - Der zurückgerechnete Thumbnail-Quellname wäre unzuverlässig, weil ein
      Originalname selbst „__" enthalten darf. Das Verzeichnis trägt dagegen
      die UUID und gehört dadurch genau einer Datei.

    Beides zieht in dieselbe Richtung: solange ein bekannter Blob im
    Verzeichnis liegt, bleibt alles darin stehen. Für den Fall, um den es geht
    — einen kompletten Bestand aus einem früheren Migrationslauf — ändert das
    nichts, dort ist kein einziges Verzeichnis mehr bekannt.
    """
    verzeichnisse = {posixpath.dirname(p) for p in bekannte if p}
    waisen = [
        pfad
        for pfad in gefundene
        if (
            (verzeichnis := zugeordnetes_verzeichnis(
                pfad, blob_praefix, thumbnail_praefix
            )) is not None
            and verzeichnis not in verzeichnisse
        )
    ]
    return sorted(waisen)
