"""Ablage: der einzige Weg, eine Datei in einen Ordner zu bringen.

**Ein Name, eine Datei.** In einem Ordner trägt ein Name genau eine Datei, ohne
Rücksicht auf Groß- und Kleinschreibung (so vergleicht auch MariaDB). Trifft eine
Ablage auf einen vergebenen Namen, legt sie keine zweite Zeile an, sondern macht
die hinzukommende Datei zur Fassung der vorhandenen. Welcher Weg was tut
(Upload, Kopieren, Referenz, Verschieben, Umbenennen, Systemablage), steht als
Tabelle in docs/files.md, „One name per folder".

**Identität.** Eine Datei ist ihr Blob (`File.file`): mehrere Zeilen auf
denselben Speicherpfad sind dieselbe Datei in mehreren Ordnern (Referenzen),
filers eigene Semantik — `File.delete()` lässt den Blob erst mit der letzten
Zeile gehen. Die **Kette** einer Datei ist ihre aktuelle Fassung plus die
`DateiVersion`-Zeilen mit `aktuell` = ihr Pfad.

**Eine Operation.** Neue Fassung (Upload, Kopie), Verschmelzen (Referenz,
Verschieben, Umbenennen) und Wiederherstellen sind alle `zusammenfuehren()`:
zwei Ketten werden zu einer, alle Zeilen beider Blobs zeigen danach auf die
vordere Fassung. Die Regel steckt in `kette_bilden()` — ohne DB, damit sie sich
prüfen lässt: Fassungen sind nach „Geändert" sortiert, vorne steht die jüngste,
und von identischen bleibt nur die älteste.
"""

import hashlib
import logging
import mimetypes
from collections import namedtuple
from datetime import datetime

from django.core.files.base import ContentFile
from django.db import transaction
from easy_thumbnails.files import get_thumbnailer
from filer.models import File, Folder

from .models import DateiIndex, DateiVersion

logger = logging.getLogger(__name__)


# === Reine Logik ==============================================================

# Eine Fassung einer Datei: die aktuelle (aus der File-Zeile) oder eine
# archivierte (aus DateiVersion). `datum` ist ihr Stand, nicht der Zeitpunkt, an
# dem sie archiviert wurde.
Fassung = namedtuple("Fassung", "pfad sha1 datum groesse mime name autor_id")

def kette_bilden(ziel, eingehend, jetzt=None):
    """Zwei Ketten (je aktuelle Fassung zuerst) zu einer.

    Liefert `(aktuell, versionen, ueberzaehlig)`. Die Regel:

    * `jetzt` gibt der eingehenden vorderen Fassung dieses Datum („Datum auf
      jetzt", Wiederherstellen).
    * Gleicher Pfad ist dieselbe Fassung; es gilt die eingehende Sicht, denn nur
      sie trägt ein gesetztes `jetzt`.
    * Von identischen Inhalten bleibt die **älteste** (bei Gleichstand die
      zuerst gelesene, Ziel vor Eingehend); die Pfade der übrigen sind
      überzählig. Ein leerer SHA-1 (Altbestand) ist nie doppelt.
    * Sortiert nach Datum: die jüngste steht vorne, die übrigen sind die
      Versionen, aufsteigend (Index + 1 ist ihre Nummer). Bei Gleichstand
      gewinnt die eingehende."""
    eingehend = list(eingehend)
    if jetzt is not None and eingehend:
        eingehend[0] = eingehend[0]._replace(datum=jetzt)

    nach_pfad = {}
    for fassung in list(ziel) + eingehend:
        nach_pfad[fassung.pfad] = fassung   # Reihenfolge des ersten Auftretens bleibt

    behalten, ueberzaehlig, aelteste = [], [], {}
    for fassung in nach_pfad.values():
        bisher = aelteste.get(fassung.sha1) if fassung.sha1 else None
        if bisher is None:
            if fassung.sha1:
                aelteste[fassung.sha1] = fassung
            behalten.append(fassung)
        elif fassung.datum < bisher.datum:
            behalten[behalten.index(bisher)] = fassung
            aelteste[fassung.sha1] = fassung
            ueberzaehlig.append(bisher.pfad)
        else:
            ueberzaehlig.append(fassung.pfad)

    behalten.sort(key=lambda f: f.datum)   # stabil: Ziel vor Eingehend
    return behalten[-1], behalten[:-1], ueberzaehlig


# Konfliktarten, wenn im Zielordner schon eine Datei dieses Namens liegt.
ART_VORHANDEN = "vorhanden"       # dieselbe Datei (gleicher Blob) liegt schon dort
ART_IDENTISCH = "identisch"       # gleicher Inhalt wie eine Fassung der Zieldatei
ART_NAME = "name"                 # anderer Inhalt, die hinzukommende ist jünger
ART_NAME_AELTER = "name_aelter"   # anderer Inhalt, die Zieldatei ist jünger
ART_GESPERRT = "gesperrt"         # die Zieldatei darf dieser Nutzer nicht ändern


def konflikt_art(ziel_inhalte, eingehend_sha1, ziel_datum, eingehend_datum):
    """Welcher Konflikt entsteht, wenn eine Datei auf eine gleichnamige trifft.

    `ziel_inhalte` sind die SHA-1 aller Fassungen der Zieldatei. Ein leerer
    SHA-1 (Altbestand) gilt nie als identisch."""
    if eingehend_sha1 and eingehend_sha1 in ziel_inhalte:
        return ART_IDENTISCH
    if ziel_datum and eingehend_datum and eingehend_datum < ziel_datum:
        return ART_NAME_AELTER
    return ART_NAME


# Was der Nutzer je Weg und Konfliktart wählen darf — außer „abbrechen", das
# immer geht. Ein Konflikt ohne gültige Wahl wird übersprungen, nie still
# verschmolzen. Kopieren fragt nicht (gleicher Name wird Fassung, gleicher
# Inhalt wird nicht abgelegt), die Systemablage auch nicht.
OPTIONEN = {
    ("verschieben", ART_NAME): ("verschmelzen",),
    ("verschieben", ART_NAME_AELTER): ("jetzt", "einsortieren"),
    ("verschieben", ART_IDENTISCH): ("loeschen",),
    ("verschieben", ART_VORHANDEN): ("loeschen",),
    ("verknuepfen", ART_NAME): ("verschmelzen",),
    ("verknuepfen", ART_NAME_AELTER): ("jetzt", "einsortieren"),
    ("verknuepfen", ART_IDENTISCH): ("verschmelzen",),
    ("umbenennen", ART_NAME): ("verschmelzen",),
    ("umbenennen", ART_NAME_AELTER): ("jetzt", "einsortieren"),
    ("umbenennen", ART_IDENTISCH): ("verschmelzen",),
    # Altbestand: dieselbe Datei liegt doppelt im Ordner — Verschmelzen räumt
    # die zweite Zeile weg.
    ("umbenennen", ART_VORHANDEN): ("verschmelzen",),
}


def konflikt_schluessel(datei_pk, ordner_id):
    """Der Schlüssel, unter dem eine Entscheidung zurückkommt."""
    return f"File:{datei_pk}@{ordner_id or 0}"


def entscheidungen_lesen(werte):
    """`["File:3@7=verschmelzen", …]` → `{"File:3@7": "verschmelzen"}`.

    Unbekannte Werte fallen weg; ob ein Wert zur Konfliktart passt, prüft
    `wahl()` erst, wenn der Konflikt feststeht."""
    erlaubt = {w for optionen in OPTIONEN.values() for w in optionen} | {"abbrechen"}
    ergebnis = {}
    for roh in werte:
        schluessel, _, wert = (roh or "").partition("=")
        if schluessel and wert in erlaubt:
            ergebnis[schluessel] = wert
    return ergebnis


def wahl(aktion, art, entscheidung):
    """Die gültige Wahl für einen Konflikt oder None (= überspringen)."""
    if entscheidung in OPTIONEN.get((aktion, art), ()):
        return entscheidung
    return None


def name_frei(vorhandene, name):
    """Ob `name` neben `vorhandene` noch frei ist — ohne Rücksicht auf
    Groß-/Kleinschreibung, wie MariaDB unter utf8mb4_general_ci vergleicht."""
    gesucht = (name or "").strip().casefold()
    return all((n or "").strip().casefold() != gesucht for n in vorhandene)


# === Identität: ein Blob, viele Ordner ========================================


def verknuepfte_dateien(f, inklusive_selbst=True):
    """All File rows sharing `f`'s blob — the same file in other folders.

    A row without a blob is only ever itself: `file` is nullable in filer, and
    matching on an empty path would lump all such rows together."""
    if not f.file or not f.file.name:
        qs = File.objects.filter(pk=f.pk)
    else:
        qs = File.objects.filter(file=f.file.name, is_public=f.is_public)
    if not inklusive_selbst:
        qs = qs.exclude(pk=f.pk)
    return qs


def datei_umbenennen(f, neuer_name):
    """Rename a file everywhere it is linked — one file, one name.

    No conflict check: `umbenennen()` and `systemablage()` call this only once
    the name is known to be free, or right before merging into its holder."""
    verknuepfte_dateien(f).update(name=neuer_name, original_filename=neuer_name)
    f.name = neuer_name
    f.original_filename = neuer_name


def versionen_loeschen(f):
    """Delete the archived blobs of `f`, for when its last row goes.

    Without this the content of a deleted file would survive in storage, which
    would undercut the deletion promise of the privacy policy."""
    versionen = list(DateiVersion.objects.filter(aktuell=f.file.name))
    DateiVersion.objects.filter(pk__in=[v.pk for v in versionen]).delete()
    _blobs_entsorgen([v.pfad for v in versionen])
    return len(versionen)


def datei_loeschen(f):
    """Remove one occurrence of a file.

    filer's File.delete() drops the blob only when no other row references it,
    so a file linked into several folders survives losing one of them. When this
    *was* the last occurrence, its archived versions go too — otherwise the
    content of a deleted file would live on in storage.

    Pass a freshly loaded instance: the decision is made on `f.file.name`, and a
    stale one would have filer delete a blob that is still in use."""
    if not verknuepfte_dateien(f, inklusive_selbst=False).exists():
        versionen_loeschen(f)
    f.delete()


def ordner_pfad(folder):
    """Full path string of a folder, e.g. "Verwaltung / Mitglieder"."""
    if folder is None:
        return "/ (Wurzel)"
    teile, cur, gesehen = [], folder, set()
    while cur is not None and cur.pk not in gesehen:
        gesehen.add(cur.pk)
        teile.append(cur.name)
        cur = cur.parent
    return " / ".join(reversed(teile))


def _speicher():
    return File._meta.get_field("file").storage


def _blobs_entsorgen(pfade):
    """Delete blobs no row and no version points at any more — with thumbnails."""
    speicher = _speicher()
    for pfad in set(pfade):
        if not pfad:
            continue
        if File.objects.filter(file=pfad).exists() or DateiVersion.objects.filter(pfad=pfad).exists():
            continue
        try:
            get_thumbnailer(pfad).delete_thumbnails()
        except Exception:
            logger.debug("Thumbnails von %s nicht löschbar", pfad)
        try:
            speicher.delete(pfad)
        except Exception:
            logger.warning("Blob %s konnte nicht gelöscht werden", pfad)


# === Ketten lesen und zusammenführen ==========================================


def fassungen(f):
    """Die Kette von `f`: aktuelle Fassung zuerst, dann die archivierten."""
    vorne = Fassung(
        f.file.name, f.sha1 or "", f.modified_at, f._file_size or 0,
        f.mime_type or "", f.original_filename or f.name or "", f.owner_id,
    )
    archiv = [
        Fassung(v.pfad, v.sha1, v.datum, v.groesse, v.mime_type, v.original_filename, v.autor_id)
        for v in DateiVersion.objects.filter(aktuell=f.file.name)
    ]
    return [vorne] + archiv


def fassung_von(f, sha1):
    """Die Fassung von `f` mit diesem Inhalt, sonst None."""
    if not sha1:
        return None
    return next((fa for fa in fassungen(f) if fa.sha1 == sha1), None)


def _sha1(inhalt):
    sha = hashlib.sha1()
    inhalt.seek(0)
    for stueck in inhalt.chunks():
        sha.update(stueck)
    inhalt.seek(0)
    return sha.hexdigest()


def _inhalt_speichern(inhalt, name, autor_id, jetzt):
    """Legt `inhalt` als neuen Blob ab, ohne Zeile — als Fassung für
    `zusammenfuehren()`. Pfad und Speicher wie bei filer selbst."""
    feld = File._meta.get_field("file")
    sha1 = _sha1(inhalt)
    pfad = _speicher().save(feld.generate_filename(File(original_filename=name), name), inhalt)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Fassung(pfad, sha1, jetzt, inhalt.size or 0, mime, name, autor_id)


def zusammenfuehren(ziel, eingehend, eingehend_zeile=None, jetzt=None):
    """Die Kette `eingehend` (aktuelle Fassung zuerst) geht in `ziel` auf.

    Danach zeigen alle Zeilen beider Blobs auf die vordere Fassung und tragen
    den Namen von `ziel`; wer vorne steht, entscheidet `kette_bilden()`.
    `jetzt` ist „Datum auf jetzt" für die eingehende Fassung.
    `eingehend_zeile` — die Zeile, die im Zielordner keinen Platz hat — gibt
    ihre ID-Verweise an `ziel` ab und verschwindet. Inhalte, die doppelt in der
    Kette stecken, gehen samt Blob, sobald nichts mehr auf sie zeigt."""
    from .verwendung import verweise_umhaengen

    ziel_kette = fassungen(ziel)
    aktuell, versionen, ueberzaehlig = kette_bilden(ziel_kette, eingehend, jetzt)
    alte = {ziel_kette[0].pfad, eingehend[0].pfad}
    name = ziel.original_filename or ziel.name

    with transaction.atomic():
        zeilen = File.objects.filter(file__in=alte, is_public=ziel.is_public)
        if eingehend_zeile is not None:
            zeilen = zeilen.exclude(pk=eingehend_zeile.pk)
        pks = list(zeilen.values_list("pk", flat=True))
        File.objects.filter(pk__in=pks).update(
            file=aktuell.pfad,
            _file_size=aktuell.groesse,
            sha1=aktuell.sha1,
            mime_type=aktuell.mime,
            modified_at=aktuell.datum,
            name=name,
            original_filename=name,
        )
        # Besitzer der Zielzeile ist, wer die vordere Fassung gebracht hat —
        # nur wenn sie gewechselt hat.
        if aktuell.pfad != ziel_kette[0].pfad and aktuell.autor_id:
            File.objects.filter(pk=ziel.pk).update(owner_id=aktuell.autor_id)
        # ensure_indexed() erkennt veraltete Einträge an der Größe; ein neuer
        # Inhalt gleicher Größe würde sonst nie neu indiziert.
        DateiIndex.objects.filter(file_id__in=pks).delete()

        DateiVersion.objects.filter(aktuell__in=alte | {aktuell.pfad}).delete()
        DateiVersion.objects.bulk_create([
            DateiVersion(
                aktuell=aktuell.pfad,
                pfad=v.pfad,
                original_filename=v.name,
                groesse=v.groesse,
                sha1=v.sha1,
                mime_type=v.mime,
                autor_id=v.autor_id,
                datum=v.datum,
                nummer=i + 1,
            )
            for i, v in enumerate(versionen)
        ])

        if eingehend_zeile is not None and eingehend_zeile.pk != ziel.pk:
            verweise_umhaengen(eingehend_zeile.pk, ziel.pk)
            # Queryset- statt Modell-delete(): filers File.delete() würde den
            # Blob wegräumen, der nun als Fassung weiterlebt. Was wirklich
            # verwaist, entsorgt _blobs_entsorgen.
            File.objects.filter(pk=eingehend_zeile.pk).delete()

        transaction.on_commit(lambda: _blobs_entsorgen(ueberzaehlig))

    ziel.refresh_from_db()
    return ziel


def wiederherstellen(f, version):
    """`version` nach vorne holen. Ihr „Geändert" wird jetzt — sonst stünde sie
    nach der Sortierung nicht vorne. Der Name bleibt: Fassungen haben keinen
    eigenen Namen."""
    eingehend = [Fassung(
        version.pfad, version.sha1, version.datum, version.groesse,
        version.mime_type, version.original_filename, version.autor_id,
    )]
    return zusammenfuehren(f, eingehend, jetzt=datetime.now())


# === Konflikte erkennen =======================================================


def gleichnamige(ordner_id, name, ausser_pk=None):
    """Die Datei, die im Ordner schon `name` trägt, sonst None."""
    qs = File.objects.filter(folder_id=ordner_id, original_filename__iexact=(name or "").strip())
    if ausser_pk is not None:
        qs = qs.exclude(pk=ausser_pk)
    return qs.select_related("folder").order_by("-modified_at").first()


def ordnername_frei(parent_id, name, ausser_pk=None):
    """Ob im Ordner `parent_id` noch kein Unterordner `name` heißt."""
    qs = Folder.objects.filter(parent_id=parent_id)
    if ausser_pk is not None:
        qs = qs.exclude(pk=ausser_pk)
    return name_frei(qs.values_list("name", flat=True), name)


class Konflikt:
    """Eine Datei trifft im Zielordner auf eine gleichnamige."""

    def __init__(self, aktion, zeile, ordner_id, ziel, art, eingehend_datum):
        self.aktion = aktion
        self.zeile = zeile
        self.ordner_id = ordner_id
        self.ziel = ziel
        self.art = art
        self.eingehend_datum = eingehend_datum
        self.schluessel = konflikt_schluessel(zeile.pk, ordner_id)

    def als_json(self):
        return {
            "schluessel": self.schluessel,
            "datei": self.ziel.original_filename or self.ziel.name,
            "ordner": ordner_pfad(self.ziel.folder),
            "art": self.art,
            "optionen": list(OPTIONEN.get((self.aktion, self.art), ())),
            "ziel_datum": self.ziel.modified_at.strftime("%-d.%-m.%Y %H:%M"),
            "eingehend_datum": self.eingehend_datum.strftime("%-d.%-m.%Y %H:%M"),
        }


def pruefen(aktion, f, ordner_id, user, name=None, jetzt=None):
    """Der Konflikt, den `aktion` mit `f` im Ordner `ordner_id` auslöst, oder None.

    Kopieren zählt als neuer Stand („jetzt"), die anderen Wege bringen das
    Datum der Datei mit."""
    from .avatar_access import darf_avatar_aendern
    from .folder_access import folder_access

    name = name or f.original_filename or f.name
    ziel = gleichnamige(ordner_id, name, ausser_pk=f.pk)
    if ziel is None:
        return None
    eingehend_datum = (jetzt or datetime.now()) if aktion == "kopieren" else f.modified_at
    if not darf_avatar_aendern(user, ziel) or not folder_access(user, ziel.folder)[1]:
        art = ART_GESPERRT
    elif ziel.file.name == f.file.name:
        art = ART_VORHANDEN
    else:
        art = konflikt_art(
            {fa.sha1 for fa in fassungen(ziel) if fa.sha1},
            f.sha1, ziel.modified_at, eingehend_datum,
        )
    return Konflikt(aktion, f, ordner_id, ziel, art, eingehend_datum)


def _aufloesen(konflikt, entscheidungen):
    """Merge `konflikt` per the user's choice. Returns the outcome."""
    gewaehlt = wahl(konflikt.aktion, konflikt.art, entscheidungen.get(konflikt.schluessel))
    if gewaehlt is None:
        return "uebersprungen"
    if gewaehlt == "loeschen":
        from .verwendung import verweise_umhaengen

        verweise_umhaengen(konflikt.zeile.pk, konflikt.ziel.pk)
        datei_loeschen(File.objects.get(pk=konflikt.zeile.pk))
        return "geloescht"
    # „jetzt" holt eine ältere Fassung nach vorne; sonst entscheidet das Datum
    # (jünger: vorne, älter: einsortiert).
    jetzt = datetime.now() if gewaehlt == "jetzt" else None
    weg = konflikt.zeile if konflikt.aktion != "verknuepfen" else None
    zusammenfuehren(konflikt.ziel, fassungen(konflikt.zeile), eingehend_zeile=weg, jetzt=jetzt)
    return "verschmolzen"


# === Die Ablagewege ===========================================================


def verschieben(f, ordner_id, user, entscheidungen):
    """`f` in `ordner_id` verschieben — oder mit der gleichnamigen Datei dort
    verschmelzen bzw. hier löschen, wenn der Inhalt dort schon liegt."""
    konflikt = pruefen("verschieben", f, ordner_id, user)
    if konflikt is None:
        File.objects.filter(pk=f.pk).update(folder_id=ordner_id)
        return "ok"
    return _aufloesen(konflikt, entscheidungen)


def verknuepfen(f, ordner_id, user, entscheidungen, owner=None):
    """Eine Referenz von `f` in `ordner_id` anlegen — eine neue Zeile auf
    denselben Blob, oder das Verschmelzen mit der gleichnamigen Datei dort."""
    konflikt = pruefen("verknuepfen", f, ordner_id, user)
    if konflikt is None:
        File.objects.create(
            file=f.file,
            original_filename=f.original_filename,
            name=f.name,
            owner=owner or user,
            folder_id=ordner_id,
            mime_type=f.mime_type,
        )
        return "ok"
    if konflikt.art == ART_VORHANDEN:
        return "vorhanden"
    return _aufloesen(konflikt, entscheidungen)


def kopieren(f, ordner_id, user, owner=None, jetzt=None):
    """Eine unabhängige Kopie von `f` in `ordner_id` — gleicher Name wird ohne
    Rückfrage neue Fassung der Datei dort, gleicher Inhalt wird nicht abgelegt."""
    jetzt = jetzt or datetime.now()
    konflikt = pruefen("kopieren", f, ordner_id, user, jetzt=jetzt)
    if konflikt is not None and konflikt.art in (ART_VORHANDEN, ART_IDENTISCH, ART_GESPERRT):
        return konflikt.art
    name = f.original_filename or f.name
    with f.file.open("rb") as quelle:
        inhalt = ContentFile(quelle.read(), name=name)
    if konflikt is None:
        File.objects.create(
            file=inhalt,
            original_filename=f.original_filename,
            name=f.name,
            owner=owner or user,
            folder_id=ordner_id,
            mime_type=f.mime_type,
        )
        return "ok"
    neu = _inhalt_speichern(inhalt, name, (owner or user).pk, jetzt)
    zusammenfuehren(konflikt.ziel, [neu])
    return "fassung"


def umbenennen(f, neuer_name, user, entscheidungen):
    """`f` überall umbenennen, wo es liegt. Trifft der Name in einem dieser
    Ordner auf eine andere Datei, wird `f` dort zu deren Fassung — sofern für
    jeden dieser Ordner eine Wahl vorliegt.

    Liefert `(status, konflikte)`: "ok", "offen" (Wahl fehlt; die Konflikte
    gehen an den Dialog), "abgebrochen" oder "gesperrt"."""
    konflikte = [
        k for k in (
            pruefen("umbenennen", zeile, zeile.folder_id, user, name=neuer_name)
            for zeile in verknuepfte_dateien(f).select_related("folder")
        )
        if k is not None
    ]
    if any(k.art == ART_GESPERRT for k in konflikte):
        return "gesperrt", konflikte
    gewaehlt = [entscheidungen.get(k.schluessel) for k in konflikte]
    if "abbrechen" in gewaehlt:
        return "abgebrochen", konflikte
    if any(wahl(k.aktion, k.art, w) is None for k, w in zip(konflikte, gewaehlt)):
        return "offen", konflikte

    datei_umbenennen(f, neuer_name)
    for k in konflikte:
        # Nach dem ersten Verschmelzen zeigt die Zeile womöglich auf einen
        # neuen Blob — frisch lesen.
        k.zeile = File.objects.get(pk=k.zeile.pk)
        _aufloesen(k, entscheidungen)
    return "ok", konflikte


def hochladen(datei, ordner_id, name, owner, jetzt=None):
    """Ein Upload nach `ordner_id` unter `name`.

    Liefert `(zeile, status, fassung)`: "neu", "fassung" (neue vordere Fassung
    der gleichnamigen Datei) oder "identisch" — dann ist nichts abgelegt und
    `fassung` die vorhandene mit diesem Inhalt."""
    jetzt = jetzt or datetime.now()
    ziel = gleichnamige(ordner_id, name)
    if ziel is None:
        zeile = File.objects.create(
            file=datei, original_filename=name, name=name, owner=owner, folder_id=ordner_id,
        )
        return zeile, "neu", None
    vorhanden = fassung_von(ziel, _sha1(datei))
    if vorhanden is not None:
        return ziel, "identisch", vorhanden
    neu = _inhalt_speichern(datei, ziel.original_filename or name, owner.pk if owner else None, jetzt)
    return zusammenfuehren(ziel, [neu]), "fassung", None


def systemablage(zeile, ordner_id, name):
    """Eine frisch hochgeladene Zeile dorthin legen, wo das Portal sie
    erwartet (Profilbild, Titel-Datei, Forenbild) — ohne Rückfrage.

    Liegt dort schon eine Datei dieses Namens, wird die neue ihre vordere
    Fassung (oder, bei gleichem Inhalt, verworfen). Zurück kommt die Zeile, auf
    die das Portal künftig verweisen soll."""
    ziel = gleichnamige(ordner_id, name, ausser_pk=zeile.pk)
    if ziel is None:
        datei_umbenennen(zeile, name)
        File.objects.filter(pk=zeile.pk).update(folder_id=ordner_id)
        zeile.folder_id = ordner_id
        return zeile
    if ziel.file.name == zeile.file.name or fassung_von(ziel, zeile.sha1) is not None:
        from .verwendung import verweise_umhaengen

        verweise_umhaengen(zeile.pk, ziel.pk)
        datei_loeschen(File.objects.get(pk=zeile.pk))
        return ziel
    return zusammenfuehren(ziel, fassungen(zeile), eingehend_zeile=zeile, jetzt=datetime.now())


def systemablage_inhalt(inhalt, ordner_id, name, owner, mime=None):
    """Wie `systemablage()`, aber für Inhalt, den das Portal selbst erzeugt
    (Antrags-PDF, entpacktes Archiv)."""
    ziel = gleichnamige(ordner_id, name)
    if ziel is None:
        return File.objects.create(
            file=inhalt, original_filename=name, name=name, owner=owner,
            folder_id=ordner_id, mime_type=mime or mimetypes.guess_type(name)[0] or "",
        )
    if fassung_von(ziel, _sha1(inhalt)) is not None:
        return ziel
    neu = _inhalt_speichern(inhalt, ziel.original_filename or name, owner.pk if owner else None, datetime.now())
    return zusammenfuehren(ziel, [neu])
