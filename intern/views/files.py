import logging
import mimetypes
import os
import zipfile
from collections import defaultdict
from pathlib import PurePosixPath

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from easy_thumbnails.files import get_thumbnailer
from filer.models import File, Folder

from intern import dateiablage, folders, liedablage, liedrollen
from intern.avatar_access import darf_avatar_aendern
from intern.dateiablage import ordner_pfad, verknuepfte_dateien
from intern.folder_access import folder_access, visible_folder_ids

from ..app_settings import get_config
from ..models import DateiVersion, Lied, TabellenPreferenzen, Termin
from ..verwendung import datei_verwendungen

__all__ = [
    "upload",
    "file_search",
    "visible_fields",
    "file_unzip",
    "datei_view",
    "datei_restore",
    "datei_verwendung",
    "datei_aktionen",
    "besitz_uebertragen",
    "_get_file_extension",
]

logger = logging.getLogger(__name__)


# === Datei-URLs ==============================================================
#
# Identität, Versionen und jede Ablage in einen Ordner liegen in
# intern/dateiablage.py — hier nur, was die Anzeige braucht.


# Der Storage des filer-Dateifelds — einmal ermittelt, danach wiederverwendet.
# Die Titelliste ruft datei_url() 639-mal je Aufruf.
_datei_storage = None


def datei_url(pfad):
    """Öffentliche URL zu einem Speicherpfad — ohne die Datei zu laden.

    Eine Liste braucht von ihren Dateien meist nur die URL. Dafür das ganze
    ``File`` zu laden ist teuer: filer legt pro Zeile ein
    ``MultiStorageFieldFile`` an, das wiederum ein easy-thumbnails-Objekt baut.
    Über 206 Titel gemessen kostete der Aufbau der Wiedergabelisten so 72,7 ms,
    mit ``values_list`` auf ``…__file`` und diesem Helfer 2,9 ms — bei gleichen
    URLs.

    Der Speicherpfad ist die Identität einer Datei (siehe oben), der Storage
    stammt deshalb vom Feld selbst und nicht vom Vorgabe-Storage: filer kann
    öffentliche Dateien woanders ablegen als Django.

    Gilt für öffentliche Dateien — das sind im Portal alle, den Zugriff regelt
    ``media_auth`` (siehe ``views/media.py``) und nicht filers privater Storage.
    Für ein ``File`` mit ``is_public=False`` bliebe ``File.url`` die richtige
    Quelle.
    """
    if not pfad:
        return ""
    global _datei_storage
    if _datei_storage is None:
        # Erst beim ersten Aufruf, nicht beim Import: zur Importzeit stehen
        # Modelle und Einstellungen noch nicht bereit (siehe CLAUDE.md).
        _datei_storage = File._meta.get_field("file").storage
    return _datei_storage.url(pfad)


def _ziel_owner(ordner, ausgeschlossen_pk, fallback_pk, cache):
    """Walk up from `ordner` to the first folder owned by somebody other than the
    member that is going away. Nothing found by the root — `fallback_pk`.

    Reads nothing but `pk`, `owner_id` and `parent`, so it can be unit-tested
    without a database. `cache` maps folder pk → resolved owner: every folder on
    the way up resolves to the same owner as the one below it, so a whole chain
    is worth caching after one walk."""
    kette = []
    ziel = fallback_pk
    gesehen = set()
    while ordner is not None and ordner.pk not in gesehen:
        gesehen.add(ordner.pk)
        if ordner.pk in cache:
            ziel = cache[ordner.pk]
            break
        kette.append(ordner.pk)
        if ordner.owner_id and ordner.owner_id != ausgeschlossen_pk:
            ziel = ordner.owner_id
            break
        ordner = ordner.parent
    for pk in kette:
        cache[pk] = ziel
    return ziel


def besitz_uebertragen(member, fallback=None):
    """Hand a departing member's files and folders to the owner of the folder
    above them. Returns `(dateien, ordner)` counts.

    Without this, filer's `on_delete=SET_NULL` leaves `owner` empty on a hard
    delete — no name in the listing, and filer's own permission check loses its
    owner branch — while an anonymised member goes on owning their files under
    the placeholder name. `fallback` takes over where the walk runs out of
    folders: the root level, an unfiled file, or a chain that belongs to the
    member all the way up."""
    fallback_pk = getattr(fallback, "pk", None)
    if fallback_pk == member.pk:
        fallback_pk = None
    cache = {}

    def _gruppiert(objekte, start):
        ziele = defaultdict(list)
        for obj in objekte:
            ziele[_ziel_owner(start(obj), member.pk, fallback_pk, cache)].append(obj.pk)
        return ziele

    dateien = _gruppiert(
        File.objects.filter(owner=member).select_related("folder"),
        lambda f: f.folder,
    )
    for ziel, pks in dateien.items():
        # Queryset update, not save(): save() fires on_filer_file_saved, which
        # spawns an indexing thread plus three thumbnail threads per file —
        # pointless here, the owner changes neither index nor thumbnail.
        File.objects.filter(pk__in=pks).update(owner_id=ziel)

    ordner = _gruppiert(
        Folder.objects.filter(owner=member).select_related("parent"),
        lambda o: o.parent,
    )
    for ziel, pks in ordner.items():
        Folder.objects.filter(pk__in=pks).update(owner_id=ziel)

    anzahl = (
        sum(len(pks) for pks in dateien.values()),
        sum(len(pks) for pks in ordner.values()),
    )
    if any(anzahl):
        logger.info(
            "Besitz von %s übertragen: %s Dateien, %s Ordner",
            member.pk,
            *anzahl,
        )
    return anzahl


def _get_file_extension(filename):
    """Extract file extension from filename"""
    return os.path.splitext(filename)[1].lower()


def _rolle_fuer_upload(filename):
    """Die Rolle, die eine hochgeladene Datei vorschlägt — Aufnahme am Präfix.

    Die Endung entscheidet; ``.mp3`` schlägt ``original`` vor, und nur der
    Aufnahme-Präfix macht daraus ``aufnahme``. Unbekannte Endungen ergeben
    ``None``: Die Datei landet ohne Rolle im Lied-Ordner."""
    rolle = liedrollen.rolle_fuer_endung(_get_file_extension(filename))
    if rolle in ("original", "aufnahme"):
        stem = os.path.splitext(os.path.basename(filename))[0]
        # `Chor - Titel` und `Chor-Titel` sind historisch gleichwertig; das
        # Präfix selbst ist konfigurierbar (FILE_PREFIX).
        p = get_config("FILE_PREFIX", "Chor")
        if stem.startswith(f"{p} - ") or stem.startswith(f"{p}-"):
            return "aufnahme"
    return rolle


@login_required
@require_POST
def upload(request):
    if not request.FILES:
        return JsonResponse(
            {"status": "error", "message": "Keine Datei übermittelt"}, status=400
        )
    from intern.app_settings import get_config_int
    from intern.folder_access import folder_access

    file = request.FILES["file"]

    max_mb = get_config_int("UPLOAD_MAX_MB", 50)
    if file.size > max_mb * 1024 * 1024:
        return JsonResponse(
            {"status": "error", "message": f"Datei zu groß (max. {max_mb} MB)"},
            status=413,
        )
    preferred_folder_id = request.POST.get("folder_id")
    extension = _get_file_extension(file.name)

    # Repertoire-Upload: Der Titel kommt von der Liedseite, einer Zeile der
    # Liederliste oder der Medien-Karte (lied_id). Die Datei gehört dann in den
    # Lied-Ordner; die Endung schlägt die Rolle vor. Unbekannte Endungen
    # bleiben erlaubt — sie landen ohne Rolle im Ordner. Ohne das Recht wird
    # abgelehnt, statt die Datei woanders abzulegen.
    lied = None
    lied_id = request.POST.get("lied_id", "")
    if lied_id:
        if lied_id.isdigit():
            lied = Lied.objects.filter(pk=int(lied_id)).first()
        if lied is None or not request.user.has_perm("intern.change_lied"):
            return JsonResponse(
                {"status": "error", "message": "Keine Berechtigung für dieses Lied"},
                status=403,
            )
    rolle = _rolle_fuer_upload(file.name) if lied is not None else None
    # Die Medien-Karte der Bearbeiten-Seite vergibt die Rolle von Hand.
    if request.POST.get("ohne_rolle"):
        rolle = None

    # Eigenes Profilbild: die Datei landet in Profilbilder und wird sofort
    # das Profilbild des angemeldeten Mitglieds.
    avatar = request.POST.get("avatar") == "1"
    if avatar and not (file.content_type or "").startswith("image/"):
        return JsonResponse(
            {"status": "error", "message": "Nur ein Bild kann das Profilbild werden"},
            status=400,
        )

    # Terminseite: die Datei gehört dem Termin. Ordner und Name stehen
    # damit fest, und das Recht wird vor der Ablage geprüft — eine Ablehnung
    # hinterlässt keine Leiche in Termin-Anhänge.
    termin = None
    termin_id = request.POST.get("termin_id", "")
    if termin_id:
        if termin_id.isdigit():
            termin = Termin.objects.filter(pk=int(termin_id)).first()
        if termin is None or not request.user.has_perm("intern.change_termin"):
            return JsonResponse(
                {"status": "error", "message": "Keine Berechtigung für diesen Termin"},
                status=403,
            )

    # Zielordner: Termin → Termin-Anhänge, Lied → eigener Lied-Ordner,
    # sonst der vom Absender genannte Ordner. Ohne Ordner läge die Datei
    # an der Wurzel (None); die Antwort meldet das, damit die Upload-Karte
    # die Wurzel freihalten kann.
    if avatar:
        folder_id = folders.avatare()
        if not folder_id:
            return JsonResponse(
                {"status": "error", "message": "Kein Zielordner verfügbar"}, status=400
            )
    elif termin is not None:
        folder_id = folders.termine()
        if not folder_id:
            return JsonResponse(
                {"status": "error", "message": "Kein Zielordner verfügbar"}, status=400
            )
    elif lied is not None:
        folder_id = liedablage.ordner_fuer(lied)
    else:
        folder_id = preferred_folder_id if preferred_folder_id not in (None, "", "0") else None

    target_folder = Folder.objects.filter(pk=folder_id).first() if folder_id else None
    if folder_id and target_folder is None:
        return JsonResponse(
            {"status": "error", "message": "Zielordner nicht gefunden"}, status=400
        )
    _, can_write, _ = folder_access(request.user, target_folder)
    if not can_write:
        return JsonResponse(
            {"status": "error", "message": "Keine Schreibrechte für diesen Ordner"},
            status=403,
        )
    # Ohne Zielordner läge die Datei auf oberster Ebene — das darf nur, wer
    # Backstage sieht (Webmaster); alle anderen haben dort keine Dropzone.
    if folder_id is None and not request.user.has_perm("intern.manage_folder_permissions"):
        return JsonResponse(
            {"status": "error", "message": "Hier lässt sich nichts hochladen — kein Zielordner"},
            status=403,
        )

    # Der endgültige Name steht vor der Ablage fest, damit die Namensregel
    # den Namen prüft, unter dem die Datei liegen wird.
    name = file.name
    # Termin-Anhänge ist ein Ordner für alle Termine: das Datum vorn hält die
    # „Ablauf.pdf“ zweier Termine auseinander. Derselbe Name am selben Termin
    # wird eine neue Fassung.
    if termin is not None:
        name = f"{termin.datum:%Y-%m-%d} {file.name}"
    elif lied is not None and rolle:
        name = liedablage.dateiname(lied.titel, rolle, extension)
    # Feld-Dropzone und Profilbild: die Datei darf keine fremde gleichnamige
    # zu ihrer Fassung machen — sie nimmt den ersten freien Namen.
    if request.POST.get("feld") or avatar:
        name = dateiablage.freier_name(
            File.objects.filter(folder_id=folder_id).values_list("original_filename", flat=True),
            name,
        )
    vorhanden = dateiablage.gleichnamige(folder_id, name)
    if vorhanden is not None and not darf_avatar_aendern(request.user, vorhanden):
        # Vor der Ablage prüfen — sonst wäre das fremde Profilbild schon ersetzt.
        return JsonResponse(
            {"status": "error", "message": "Das ist das Profilbild eines anderen Mitglieds."},
            status=403,
        )
    # Gleicher Name: neue vordere Fassung der Datei dort (die PK bleibt, alle
    # Verweise und Referenzen folgen). Gleicher Inhalt: nichts wird abgelegt.
    filer_file, status, gleiche = dateiablage.hochladen(file, folder_id, name, request.user)
    overwritten = status == "fassung"
    meldung = ""
    if status == "identisch":
        meldung = (
            "Bereits vorhanden — nicht abgelegt"
            if gleiche.pfad == filer_file.file.name
            else f"Bereits vorhanden als Fassung vom {gleiche.datum:%-d.%-m.%Y} — nicht abgelegt"
        )

    if avatar:
        request.user.avatar = filer_file
        request.user._audit_user = request.user
        request.user.save(update_fields=["avatar"])
    elif termin is not None:
        termin.dateien.add(filer_file)
    elif lied is not None and rolle:
        liedablage.rolle_setzen(lied, rolle, filer_file, request.user)

    # Return response
    url = (request.META.get("HTTP_ORIGIN") or "") + filer_file.url
    thumb = ""
    try:
        thumb = get_thumbnailer(filer_file.file).get_thumbnail(
            {"size": (120, 120), "crop": True, "quality": 85}
        ).url
    except Exception:
        pass
    # Über `original_filename` löst ein [[Datei:…]] auf, den die
    # Artikelseiten daraus bauen.
    return JsonResponse({"status": "success", "id": filer_file.id, "name": filer_file.original_filename, "url": url, "thumbnail_url": thumb, "overwritten": overwritten, "identisch": status == "identisch", "meldung": meldung, "wurzel": folder_id is None})


def _datei_orte(f, user):
    """Every place `f` is linked into that `user` may see, plus the write flag.

    Only visible folders are listed — otherwise the page would give away the
    existence of folders the member has no access to."""
    sichtbar = visible_folder_ids(user)
    orte, darf_schreiben = [], False
    for g in verknuepfte_dateien(f).select_related("folder"):
        if g.folder_id is not None and g.folder_id not in sichtbar:
            continue
        _, can_write, _ = folder_access(user, g.folder)
        darf_schreiben = darf_schreiben or can_write
        orte.append({
            "datei": g,
            "folder": g.folder,
            "pfad": ordner_pfad(g.folder),
            "url": reverse("folder_view", args=[g.folder_id]) if g.folder_id else None,
        })
    orte.sort(key=lambda o: o["pfad"])
    return orte, darf_schreiben


def _vorschau(quelle, **opts):
    """Thumbnail URL for a file or a bare storage path, "" when none is possible.

    Versions have no `File` row — their blob is addressed by path alone, which
    `get_thumbnailer()` accepts just as it does in `versionen_loeschen()`."""
    try:
        return get_thumbnailer(quelle).get_thumbnail(
            {"quality": 85, **opts}
        ).url
    except Exception:
        return ""


@login_required
def datei_view(request, pk):
    """Detail page: where a file is linked into, and its version history."""
    f = get_object_or_404(File, pk=pk)
    orte, darf_schreiben = _datei_orte(f, request.user)
    if not orte:
        raise Http404
    versionen = list(DateiVersion.objects.filter(aktuell=f.file.name))
    for v in versionen:
        v.vorschau = _vorschau(v.pfad, size=(96, 96), crop=True)
    return render(request, "datei.html", {
        "datei": f,
        "orte": orte,
        "darf_schreiben": darf_schreiben,
        # Fremde Profilbilder bleiben einsehbar, aber nicht wiederherstellbar.
        "darf_wiederherstellen": darf_schreiben and darf_avatar_aendern(request.user, f),
        "versionen": versionen,
        "verwendungen": datei_verwendungen([f], request.user).get(f.pk, []),
        "thumbnail": _vorschau(f.file, size=(320, 320), crop=False),
        "vorschau": _vorschau(f.file, size=(96, 96), crop=True),
        "titel": f.original_filename or f.name,
    })


@login_required
@require_POST
def datei_restore(request, pk, version_id):
    """Bring an archived revision to the front — everywhere the file is linked.

    Only the order of the chain changes (`dateiablage.wiederherstellen`): the
    running revision becomes a version, no blob is copied or deleted, and the
    name stays — revisions have no name of their own."""
    f = get_object_or_404(File, pk=pk)
    orte, darf_schreiben = _datei_orte(f, request.user)
    if not orte:
        raise Http404
    if not darf_schreiben:
        raise PermissionDenied
    if not darf_avatar_aendern(request.user, f):
        raise PermissionDenied
    version = get_object_or_404(DateiVersion, pk=version_id, aktuell=f.file.name)

    dateiablage.wiederherstellen(f, version)
    return redirect("datei_view", pk=f.pk)


@login_required
@require_POST
def datei_verwendung(request):
    """Which references would break if the selection were deleted (or renamed)?

    Feeds the confirmation dialogs of the folder browser. Takes the same
    `item` list (`Type:id`) as the other selection actions; folders are
    expanded to the files they contain. With `neuer_name` set it answers for
    the rename case, where only wiki links (name-addressed) are at risk."""
    from .folders import _iter_folder_tree, _parse_items

    umbenennen = bool(request.POST.get("neuer_name"))
    sichtbar = visible_folder_ids(request.user)
    dateien, gesehen = [], set()

    def merken(f):
        if f.pk not in gesehen:
            gesehen.add(f.pk)
            dateien.append(f)

    for item_type, item_id in _parse_items(request.POST):
        if item_type == "Folder":
            folder = Folder.objects.filter(pk=item_id).first()
            if folder is None or folder.pk not in sichtbar:
                continue
            for _arcname, f in _iter_folder_tree(folder):
                merken(f)
        else:
            f = File.objects.filter(pk=item_id).first()
            if f is None or (f.folder_id is not None and f.folder_id not in sichtbar):
                continue
            merken(f)

    treffer = datei_verwendungen(dateien, request.user, beim_loeschen=not umbenennen)
    warnungen = [
        {
            "datei": f.original_filename or f.name,
            "verwendungen": [v["label"] for v in treffer[f.pk]],
            "wiki": [v["label"] for v in treffer[f.pk] if v["art"] == "wiki"],
        }
        for f in dateien
        if f.pk in treffer
    ]
    return JsonResponse({"warnungen": warnungen})


@login_required
def datei_aktionen(request, pk):
    """What the file menu of an article may offer for this one file row.

    The row is the one a `[[Datei:…]]` resolves to; its folder, the delete
    right on it and the folders a reference may go to. Deleting means this
    occurrence only, exactly as in the folder browser (`folder_delete`)."""
    from .folders import _build_folder_flat, _sieht_backstage

    f = get_object_or_404(File.objects.select_related("folder"), pk=pk)
    lesen, _, loeschen = folder_access(request.user, f.folder)
    if not lesen or (
        f.folder_id is not None and f.folder_id not in visible_folder_ids(request.user)
    ):
        raise Http404

    darf_loeschen = (
        (loeschen or request.user.has_perm("intern.delete_folder"))
        and darf_avatar_aendern(request.user, f)
    )
    belegt = set(verknuepfte_dateien(f).values_list("folder_id", flat=True))
    ordner = {o.pk: o for o in Folder.objects.all()}
    ziele = [
        e for e in _build_folder_flat(
            user=request.user,
            ohne_backstage=not _sieht_backstage(request.user),
            ohne_liedordner=True,
        )
        if e["id"] not in belegt and folder_access(request.user, ordner.get(e["id"]))[1]
    ]
    warnungen = [
        {"label": v["label"], "url": v.get("url")}
        for v in datei_verwendungen([f], request.user).get(f.pk, [])
    ]
    return JsonResponse({
        "ordner": {
            "url": reverse("folder_view", args=[f.folder_id or 0]) + f"?datei={f.pk}",
            "pfad": ordner_pfad(f.folder),
        },
        "darf_loeschen": darf_loeschen,
        "ziele": ziele,
        "warnungen": warnungen,
    })


@login_required
def file_search(request):
    q = request.GET.get("q", "")
    if not q:
        return JsonResponse([], safe=False)
    visible_ids = visible_folder_ids(request.user)
    files = (
        File.objects
        .filter(original_filename__istartswith=q)
        .filter(Q(folder_id__in=visible_ids) | Q(folder__isnull=True))
        .only("id", "original_filename", "file")[:20]
    )
    results = [{"id": f.id, "name": f.original_filename, "url": f.url} for f in files]
    return JsonResponse(results, safe=False)


def visible_fields(request, tabelle):
    visible_fields = request.POST.getlist("columns")
    if len(visible_fields) == 0:
        # Bewusst first() statt get(): der unique_together deckt die globale
        # Vorgabezeile (person=None) nicht ab, weil NULLs im Unique-Index als
        # verschieden gelten (siehe TabellenPreferenzen in models.py). Eine zweite
        # Vorgabezeile darf die Tabelle nicht mit MultipleObjectsReturned zerlegen.
        pref = (
            TabellenPreferenzen.objects.filter(person=request.user, tabelle=tabelle)
            .order_by("pk")
            .first()
        )
        if pref is None:
            pref = (
                TabellenPreferenzen.objects.filter(person=None, tabelle=tabelle)
                .order_by("pk")
                .first()
            )
        return pref.sichtbare_spalten if pref else []
    else:
        TabellenPreferenzen.objects.update_or_create(
            person=request.user,
            tabelle=tabelle,
            defaults={
                "sichtbare_spalten": visible_fields,
            },
        )
    return visible_fields


def _decode_zip_name(info):
    """Return a str filename from a ZipInfo, handling cp437-encoded legacy zips."""
    raw = info.filename
    if not raw:
        return None
    try:
        raw.encode("cp437").decode("utf-8")
        return raw
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    try:
        return raw.encode("cp437").decode("latin-1")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def _unique_folder_name(parent_id, base):
    """Generate a unique folder name under parent_id by appending -1, -2, etc."""
    existing = set(
        Folder.objects.filter(parent_id=parent_id).values_list("name", flat=True)
    )
    if base not in existing:
        return base
    n = 1
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


# Schutz gegen Zip-Bomben: Grenzen für Anzahl und entpackte Größe.
_UNZIP_MAX_ENTRIES = 500
_UNZIP_MAX_TOTAL = 500 * 1000 * 1000   # 500 MB entpackt insgesamt
_UNZIP_MAX_SINGLE = 100 * 1000 * 1000  # 100 MB pro Datei


@login_required
def file_unzip(request, pk):
    from intern.folder_access import folder_access

    src_file = get_object_or_404(File, pk=pk)
    original = (src_file.original_filename or src_file.name or "").lower()
    if not original.endswith(".zip"):
        return JsonResponse({"status": "error", "message": "Keine Zip-Datei."}, status=400)

    parent_id = src_file.folder_id
    parent_folder = Folder.objects.filter(pk=parent_id).first() if parent_id else None
    _, can_write, _ = folder_access(request.user, parent_folder)
    if not can_write:
        return JsonResponse(
            {"status": "error", "message": "Keine Schreibrechte für diesen Ordner"},
            status=403,
        )
    fh = src_file.file.open("rb")
    try:
        zf = zipfile.ZipFile(fh)
    except zipfile.BadZipFile:
        fh.close()
        return JsonResponse({"status": "error", "message": "Beschädigtes Archiv."}, status=400)

    entries = []
    total_size = 0
    for info in zf.infolist():
        name = _decode_zip_name(info)
        if not name or name.startswith("__MACOSX/") or "/.DS_Store" in name:
            continue
        if name.endswith("/"):
            continue
        parts = [p for p in PurePosixPath(name).parts if p not in (".", "")]
        if not parts or ".." in parts:
            continue
        total_size += info.file_size
        entries.append((parts, info))

    if len(entries) > _UNZIP_MAX_ENTRIES or total_size > _UNZIP_MAX_TOTAL:
        fh.close()
        return JsonResponse(
            {"status": "error", "message": "Archiv ist zu groß zum Entpacken."},
            status=400,
        )

    if not entries:
        fh.close()
        return JsonResponse({"status": "error", "message": "Leeres Archiv."}, status=400)

    top_levels = {parts[0] for parts, _ in entries}
    if len(top_levels) == 1 and any(len(parts) > 1 for parts, _ in entries):
        target_base = next(iter(top_levels))
        strip = 1
    else:
        target_base = PurePosixPath(src_file.original_filename or "archive.zip").stem or "archive"
        strip = 0

    target_name = _unique_folder_name(parent_id, target_base)
    root = Folder.objects.create(name=target_name, parent_id=parent_id, owner=request.user)

    folder_cache = {(): root}

    def ensure_folder(rel_parts):
        key = tuple(rel_parts)
        if key in folder_cache:
            return folder_cache[key]
        parent = ensure_folder(rel_parts[:-1])
        folder = Folder.objects.create(name=rel_parts[-1], parent=parent, owner=request.user)
        folder_cache[key] = folder
        return folder

    for parts, info in entries:
        effective = parts[strip:]
        if not effective:
            continue
        if info.file_size > _UNZIP_MAX_SINGLE:
            continue
        dir_parts, fname = effective[:-1], effective[-1]
        target_folder = ensure_folder(dir_parts)
        try:
            # zf.read() stoppt bei file_size aus dem Header — eine gefälschte
            # Größenangabe kann das Limit damit nicht unterlaufen.
            data = zf.read(info)
        except Exception:
            continue
        mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        # Ein Archiv kann einen Namen doppelt tragen (etwa in anderer
        # Schreibweise) — dann wird der zweite Eintrag Fassung des ersten.
        dateiablage.systemablage_inhalt(
            ContentFile(data, name=fname), target_folder.pk, fname, request.user, mime,
        )

    fh.close()
    folders.invalidate()
    return redirect("folder_view", pk=parent_id or 0)