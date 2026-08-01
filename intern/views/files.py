import logging
import mimetypes
import os
import zipfile
from pathlib import PurePosixPath

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db.models import Max
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from easy_thumbnails.files import get_thumbnailer
from filer.models import File, Folder

from intern import folders
from intern.avatar_access import darf_avatar_aendern
from intern.folder_access import folder_access, visible_folder_ids

from ..models import DateiIndex, DateiVersion, Lied, TabellenPreferenzen, User
from ..verwendung import datei_verwendungen

__all__ = [
    "upload",
    "file_search",
    "visible_fields",
    "file_unzip",
    "datei_view",
    "datei_restore",
    "datei_verwendung",
    "verknuepfte_dateien",
    "datei_umbenennen",
    "versionen_loeschen",
    "_get_file_extension",
    "_get_file_type_config",
    "_get_lied_by_filename",
    "_assign_file_to_song",
    "_route_and_rename_for_lied",
]

logger = logging.getLogger(__name__)


# === Dateiidentität: ein Blob, viele Ordner ==================================
#
# Two File rows pointing at the same storage path are the *same* file in two
# folders — folders work like tags. This is filer's own semantics: File.delete()
# drops the blob only when no other row references it. Every operation that
# changes a file's path or name therefore has to carry all its rows along, which
# is what the helpers below are for.


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
    """Rename a file everywhere it is linked — one file, one name."""
    verknuepfte_dateien(f).update(name=neuer_name, original_filename=neuer_name)
    f.name = neuer_name
    f.original_filename = neuer_name


def version_anlegen(f, autor=None):
    """Archive `f`'s current revision before its blob is replaced.

    The blob stays where it is; only its path is recorded. Callers must follow
    up with `geschwister_nachziehen()`, which moves the chain (including this
    new row) onto the new path."""
    pfad = f.file.name
    letzte = DateiVersion.objects.filter(aktuell=pfad).aggregate(Max("nummer"))
    return DateiVersion.objects.create(
        aktuell=pfad,
        pfad=pfad,
        original_filename=f.original_filename or f.name or "",
        groesse=f._file_size or 0,
        sha1=f.sha1 or "",
        mime_type=f.mime_type or "",
        autor=autor if (autor and autor.is_authenticated) else None,
        nummer=(letzte["nummer__max"] or 0) + 1,
    )


def geschwister_nachziehen(alter_pfad, quelle):
    """Point every other row that shared `alter_pfad` at `quelle`'s new blob, so
    the update shows up in all folders the file is linked into. Also moves the
    version chain over to the new path."""
    pks = list(
        File.objects.filter(file=alter_pfad, is_public=quelle.is_public)
        .exclude(pk=quelle.pk)
        .values_list("pk", flat=True)
    )
    if pks:
        File.objects.filter(pk__in=pks).update(
            file=quelle.file.name,
            _file_size=quelle._file_size,
            sha1=quelle.sha1,
            mime_type=quelle.mime_type,
        )
        # ensure_indexed() spots stale rows by file size; drop the entries so a
        # replacement of exactly the same size is re-indexed too.
        DateiIndex.objects.filter(file_id__in=pks).delete()
    DateiVersion.objects.filter(aktuell=alter_pfad).update(aktuell=quelle.file.name)
    return pks


def versionen_loeschen(f):
    """Delete the archived blobs of `f`, for when its last row goes.

    Without this the content of a deleted file would survive in storage, which
    would undercut the deletion promise of the privacy policy."""
    versionen = list(DateiVersion.objects.filter(aktuell=f.file.name))
    for v in versionen:
        try:
            get_thumbnailer(v.pfad).delete_thumbnails()
        except Exception:
            logger.debug("Thumbnails der Version %s nicht löschbar", v.pfad)
        try:
            f.file.storage.delete(v.pfad)
        except Exception:
            logger.warning("Versions-Blob %s konnte nicht gelöscht werden", v.pfad)
    DateiVersion.objects.filter(pk__in=[v.pk for v in versionen]).delete()
    return len(versionen)


def _get_file_extension(filename):
    """Extract file extension from filename"""
    return os.path.splitext(filename)[1].lower()


def _get_file_type_config(extension):
    """Get file type config for given extension"""
    for file_type, config in settings.FILE_TYPE_CONFIG.items():
        if extension in config["extensions"]:
            return file_type, config
    return None, None


def _get_lied_by_filename(filename):
    """Look up Lied object by filename (with JG- prefix support)"""
    name, _ = os.path.splitext(filename)
    try:
        if name.startswith("JG - "):
            return Lied.objects.get(titel=name[5:])
        if name.startswith("JG-"):
            return Lied.objects.get(titel=name[3:])
        return Lied.objects.get(titel=name)
    except Lied.DoesNotExist:
        return None


def _assign_file_to_song(filename, filer_file):
    """If filename matches a song title, assign filer_file to the appropriate Lied field."""
    song = _get_lied_by_filename(filename)
    if not song:
        return
    extension = _get_file_extension(filename)
    file_type, _ = _get_file_type_config(extension)
    if not file_type:
        return
    name_stem = os.path.splitext(filename)[0]
    if file_type == "audio" and name_stem.startswith(("JG - ", "JG-")):
        field_name = "aufnahme"
    else:
        field_name = settings.FILE_TYPE_LIED_MAP.get(file_type)
    if field_name:
        setattr(song, field_name, filer_file)
        song.save()


def _route_and_rename_for_lied(lied, filer_file, source_name):
    """Route a dropzone-uploaded file by its extension, rename it after the song
    title, and assign it to the matching FilerFileField on `lied`.

    The extension decides the kind: PDF → Notenblatt (`pdf`), notation files →
    Notensatz (`noten`), audio → Original/Aufnahme. An audio file uploaded with
    a "JG - " prefix counts as our own recording (`aufnahme`), otherwise as the
    reference original (`original`). Returns the assigned field name, or None
    for extensions that don't map to a known song-file type.
    """
    extension = _get_file_extension(source_name)
    file_type, _ = _get_file_type_config(extension)
    if not file_type:
        return None

    name_stem = os.path.splitext(source_name)[0]
    if file_type == "audio" and name_stem.startswith(("JG - ", "JG-")):
        field_name = "aufnahme"
    else:
        field_name = settings.FILE_TYPE_LIED_MAP.get(file_type)
    if not field_name:
        return None

    _type_folder = {
        "audio": folders.repertoire,
        "music": folders.notensatz,
        "pdf": folders.pdf,
    }
    folder_id = (_type_folder.get(file_type) or folders.unsortiert)()
    if folder_id:
        filer_file.folder_id = folder_id

    new_name = (
        f"JG - {lied.titel}{extension}"
        if field_name == "aufnahme"
        else f"{lied.titel}{extension}"
    )
    datei_umbenennen(filer_file, new_name)
    filer_file.save()

    setattr(lied, field_name, filer_file)
    lied.save(update_fields=[field_name])
    return field_name


@login_required
@require_POST
def upload(request):
    if not request.FILES:
        return JsonResponse(
            {"status": "error", "message": "Keine Datei übermittelt"}, status=400
        )
    if request.FILES:
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
        rename_to = request.POST.get("rename_to")
        avatar_user_id = request.POST.get("avatar_user_id")
        route_by_type = request.POST.get("route_by_type")

        # Extract extension
        extension = _get_file_extension(file.name)

        # Get file type config if extension is special
        file_type, file_type_config = _get_file_type_config(extension)

        # Look up song if filename matches
        song = _get_lied_by_filename(file.name)

        # Determine folder_id:
        # Use type-specific subfolder when we know the file type AND either a
        # matching song was found or the upload context explicitly requests it
        # (e.g. dropped on the Repertoire/Titel page).
        _type_folder = {"audio": folders.repertoire, "music": folders.notensatz, "pdf": folders.pdf}
        if file_type and file_type_config and (song or route_by_type):
            folder_id = (_type_folder.get(file_type) or folders.unsortiert)()
        else:
            folder_id = preferred_folder_id or folders.unsortiert()

        if not folder_id:
            return JsonResponse(
                {"status": "error", "message": "Kein Zielordner verfügbar"}, status=400
            )

        target_folder = Folder.objects.filter(pk=folder_id).first()
        _, can_write, _ = folder_access(request.user, target_folder)
        if not can_write:
            return JsonResponse(
                {"status": "error", "message": "Keine Schreibrechte für diesen Ordner"},
                status=403,
            )

        # Fremde Mitglieds-IDs nur mit Verwaltungsrecht — vor dem Anlegen der
        # Datei geprüft, damit eine Ablehnung keine Leiche im Ordner hinterlässt.
        # Sonst könnte man eine zweite "<id>.jpg" in den Avatare-Ordner schieben
        # oder das Avatar-FK eines beliebigen Mitglieds umbiegen.
        fremd_erlaubt = request.user.is_superuser or request.user.has_perm("intern.change_user")

        def _fremde_mitglieds_id(wert):
            return (
                str(wert).isdigit()
                and int(wert) != request.user.pk
                and User.objects.filter(pk=int(wert)).exists()
            )

        avatare_id = folders.avatare()
        ins_avatar_verzeichnis = avatare_id is not None and str(folder_id) == str(avatare_id)
        if not fremd_erlaubt and (
            (ins_avatar_verzeichnis and rename_to and _fremde_mitglieds_id(rename_to))
            or (avatar_user_id and _fremde_mitglieds_id(avatar_user_id))
        ):
            return JsonResponse(
                {"status": "error", "message": "Das ist das Profilbild eines anderen Mitglieds."},
                status=403,
            )

        # Overwrite in-place if a file with the same name already exists here.
        # Replacing the .file field updates content but keeps the same File PK,
        # so existing Lied/Artikel/Forum references remain intact. The previous
        # revision is kept (version_anlegen) instead of being deleted, and every
        # folder the file is linked into follows along (geschwister_nachziehen).
        existing = File.objects.filter(
            folder_id=folder_id, original_filename=file.name
        ).first()
        overwritten = existing is not None
        if overwritten and not darf_avatar_aendern(request.user, existing):
            # Vor version_anlegen prüfen — sonst wäre die fremde Fassung schon
            # archiviert und das Profilbild ersetzt.
            return JsonResponse(
                {"status": "error", "message": "Das ist das Profilbild eines anderen Mitglieds."},
                status=403,
            )
        if overwritten:
            alter_pfad = existing.file.name
            version_anlegen(existing, request.user)
            existing.file = file
            existing.owner = request.user
            existing.save()
            geschwister_nachziehen(alter_pfad, existing)
            filer_file = existing
        else:
            filer_file = File.objects.create(
                file=file,
                original_filename=file.name,
                name=file.name,
                owner=request.user,
                folder_id=folder_id,
            )

        # Rename file if requested (e.g. avatar → <user_id>.<ext>)
        if rename_to:
            ext = _get_file_extension(file.name)
            datei_umbenennen(filer_file, f"{rename_to}{ext}")

        # Update user avatar if requested
        if avatar_user_id:
            try:
                User.objects.filter(pk=int(avatar_user_id)).update(avatar=filer_file)
            except (ValueError, TypeError):
                pass

        # Assign to a song: explicitly by id when dropped on a Titel detail
        # page, otherwise by filename match.
        lied_id = request.POST.get("lied_id")
        if lied_id and request.user.has_perm("intern.change_lied"):
            try:
                lied = Lied.objects.get(pk=int(lied_id))
                _route_and_rename_for_lied(lied, filer_file, file.name)
            except (Lied.DoesNotExist, ValueError):
                pass
        else:
            _assign_file_to_song(file.name, filer_file)

        # Return response
        url = (request.META.get("HTTP_ORIGIN") or "") + filer_file.url
        thumb = ""
        try:
            thumb = get_thumbnailer(filer_file.file).get_thumbnail(
                {"size": (120, 120), "crop": True, "quality": 85}
            ).url
        except Exception:
            pass
        return JsonResponse({"status": "success", "id": filer_file.id, "url": url, "thumbnail_url": thumb, "overwritten": overwritten})


def _ordner_pfad(folder):
    """Full path string of a folder, e.g. "Verwaltung / Mitglieder"."""
    if folder is None:
        return "/ (Wurzel)"
    teile, cur, gesehen = [], folder, set()
    while cur is not None and cur.pk not in gesehen:
        gesehen.add(cur.pk)
        teile.append(cur.name)
        cur = cur.parent
    return " / ".join(reversed(teile))


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
            "pfad": _ordner_pfad(g.folder),
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
    """Make an archived revision the current one — everywhere the file is linked.

    Mirrors the overwrite path: the running revision becomes a version itself,
    all linked rows move onto the restored blob. No blob is copied or deleted."""
    f = get_object_or_404(File, pk=pk)
    orte, darf_schreiben = _datei_orte(f, request.user)
    if not orte:
        raise Http404
    if not darf_schreiben:
        raise PermissionDenied
    if not darf_avatar_aendern(request.user, f):
        raise PermissionDenied
    version = get_object_or_404(DateiVersion, pk=version_id, aktuell=f.file.name)

    alter_pfad = f.file.name
    version_anlegen(f, request.user)
    f.file = version.pfad
    f.owner = request.user
    f.save()
    geschwister_nachziehen(alter_pfad, f)
    if version.original_filename:
        datei_umbenennen(f, version.original_filename)
    version.delete()
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
def file_search(request):
    q = request.GET.get("q", "")
    if not q:
        return JsonResponse([], safe=False)
    visible_ids = visible_folder_ids(request.user)
    files = (
        File.objects
        .filter(original_filename__istartswith=q, folder_id__in=visible_ids)
        .only("id", "original_filename", "file")[:20]
    )
    results = [{"id": f.id, "name": f.original_filename, "url": f.url} for f in files]
    return JsonResponse(results, safe=False)


def visible_fields(request, tabelle):
    visible_fields = request.POST.getlist("columns")
    if len(visible_fields) == 0:
        try:
            pref = TabellenPreferenzen.objects.get(person=request.user, tabelle=tabelle)
            return pref.sichtbare_spalten
        except TabellenPreferenzen.DoesNotExist:
            try:
                pref = TabellenPreferenzen.objects.get(person=None, tabelle=tabelle)
                return pref.sichtbare_spalten
            except TabellenPreferenzen.DoesNotExist:
                return []
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
        filer_file = File.objects.create(
            file=ContentFile(data, name=fname),
            original_filename=fname,
            name=fname,
            owner=request.user,
            folder=target_folder,
            mime_type=mime,
        )
        _assign_file_to_song(fname, filer_file)

    fh.close()
    folders.invalidate()
    return redirect("folder_view", pk=parent_id or 0)