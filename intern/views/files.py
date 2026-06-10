import logging
import mimetypes
import os
import zipfile
from pathlib import PurePosixPath

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from easy_thumbnails.files import get_thumbnailer
from filer.models import File, Folder

from intern import folders

from ..models import Lied, TabellenPreferenzen, User

__all__ = [
    "upload",
    "file_search",
    "visible_fields",
    "file_unzip",
    "_get_file_extension",
    "_get_file_type_config",
    "_get_lied_by_filename",
    "_assign_file_to_song",
    "_route_and_rename_for_lied",
]

logger = logging.getLogger(__name__)


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
    filer_file.original_filename = new_name
    filer_file.name = new_name
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
        from intern.folder_access import folder_access

        file = request.FILES["file"]
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

        # Overwrite in-place if a file with the same name already exists here.
        # Replacing the .file field updates content but keeps the same File PK,
        # so existing Lied/Artikel/Forum references remain intact.
        existing = File.objects.filter(
            folder_id=folder_id, original_filename=file.name
        ).first()
        if existing is not None:
            try:
                existing.file.delete(save=False)
            except Exception:
                pass
            existing.file = file
            existing.owner = request.user
            existing.save()
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
            new_name = f"{rename_to}{ext}"
            filer_file.original_filename = new_name
            filer_file.name = new_name
            filer_file.save(update_fields=["original_filename", "name"])

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
        return JsonResponse({"status": "success", "id": filer_file.id, "url": url, "thumbnail_url": thumb})


@login_required
def file_search(request):
    from intern.folder_access import visible_folder_ids

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