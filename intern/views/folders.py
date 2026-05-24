import posixpath
import zipfile

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import (
    Count,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, Concat
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig

from easy_thumbnails.files import get_thumbnailer
from filer.models import File, Folder

from intern import folders
from intern.folder_access import (
    folder_access,
    is_folder_visible,
    visible_folder_ids,
)

from ..models import FolderPermission
from ..tables import OrdnerTabelle

__all__ = [
    "folder_view",
    "folder_create",
    "folder_delete",
    "folder_move",
    "folder_copy",
    "folder_rename",
    "folder_zip_download",
]


def _build_folder_flat(exclude_pk=None, user=None):
    """Return all folders as a flat list with full path strings, for the folder picker.

    When `user` is given, restrict the list to folders the user can read."""
    all_fldrs = list(Folder.objects.order_by("name").values("id", "name", "parent_id"))
    folder_map = {f["id"]: f for f in all_fldrs}

    def path_of(f):
        parts = [f["name"]]
        cur = f
        seen = set()
        while cur["parent_id"] and cur["parent_id"] not in seen:
            seen.add(cur["id"])
            par = folder_map.get(cur["parent_id"])
            if not par:
                break
            parts.append(par["name"])
            cur = par
        return " / ".join(reversed(parts))

    if user is not None:
        visible_ids = visible_folder_ids(user)
        all_fldrs = [f for f in all_fldrs if f["id"] in visible_ids]

    return [
        {"id": f["id"], "path": path_of(f)} for f in all_fldrs if f["id"] != exclude_pk
    ]


def _folder_breadcrumb(folder, user=None):
    """Walk parent chain and return list of {name, pk} from root → current.

    When `user` is given, the chain is truncated to start at the deepest readable
    ancestor — folders the user can't see are dropped."""
    crumbs = []
    cur = folder
    while cur:
        crumbs.append({"name": cur.name, "pk": cur.pk})
        cur = cur.parent
    crumbs.reverse()
    if user is not None and not (user.is_authenticated and user.is_superuser):
        visible_ids = visible_folder_ids(user) if user.is_authenticated else set()
        # Drop leading crumbs that aren't visible
        first_visible = 0
        for i, c in enumerate(crumbs):
            if c["pk"] in visible_ids:
                first_visible = i
                break
        crumbs = crumbs[first_visible:]
    return crumbs


def _parse_items(post):
    """Parse 'item' list of 'Type:id' strings from POST data."""
    items = []
    for raw in post.getlist("item"):
        if ":" in raw:
            t, _, i = raw.partition(":")
            items.append((t, int(i)))
    return items


def _delete_folder_deep(folder):
    """Recursively delete a folder and its contents, calling File.delete() on each
    file so filer's custom delete() also removes the underlying blob from storage."""
    for f in File.objects.filter(folder=folder).iterator():
        f.delete()
    for child in Folder.objects.filter(parent=folder):
        _delete_folder_deep(child)
    folder.delete()


def _is_descendant_or_self(candidate_id, ancestor_id):
    """True if candidate_id == ancestor_id or candidate is reachable by walking up
    parent pointers from candidate until it equals ancestor_id."""
    if candidate_id is None or ancestor_id is None:
        return False
    cur = candidate_id
    while cur is not None:
        if cur == ancestor_id:
            return True
        try:
            cur = Folder.objects.values_list("parent_id", flat=True).get(pk=cur)
        except Folder.DoesNotExist:
            return False
    return False


def _copy_folder_deep(src_folder, target_parent_id, owner):
    """Recursively copy a folder and its contents into target_parent_id.
    File records are duplicated, but their underlying storage blob is shared —
    matches filer's own copy semantics (and how single-file copy already worked)."""
    new_name = _unique_folder_name(target_parent_id, src_folder.name)
    new_folder = Folder.objects.create(
        name=new_name, parent_id=target_parent_id, owner=owner
    )
    for f in File.objects.filter(folder=src_folder):
        File.objects.create(
            file=f.file,
            original_filename=f.original_filename,
            name=f.name,
            owner=owner,
            folder=new_folder,
            mime_type=f.mime_type,
        )
    for child in Folder.objects.filter(parent=src_folder):
        _copy_folder_deep(child, new_folder.pk, owner)
    return new_folder


def _validate_rename(name):
    name = (name or "").strip()
    if not name or len(name) > 255 or "/" in name or "\\" in name or name in (".", ".."):
        return None
    return name


def _iter_folder_tree(folder, prefix=""):
    """Yield (arcname, filer_file) tuples for a folder and its descendants."""
    for f in File.objects.filter(folder=folder):
        name = f.original_filename or f.name or f"file-{f.pk}"
        yield posixpath.join(prefix, name) if prefix else name, f
    for child in Folder.objects.filter(parent=folder).order_by("name"):
        child_prefix = posixpath.join(prefix, child.name) if prefix else child.name
        yield from _iter_folder_tree(child, child_prefix)


class _ZipBuffer:
    def __init__(self):
        self._buf = bytearray()
        self._pos = 0

    def write(self, data):
        self._buf.extend(data)
        self._pos += len(data)
        return len(data)

    def drain(self):
        data = bytes(self._buf)
        self._buf.clear()
        return data

    def tell(self):
        return self._pos

    def flush(self):
        pass


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


def _descendant_folder_ids(pk):
    """Return the set of folder ids for pk and all its descendants (iterative BFS)."""
    ids = {pk}
    frontier = [pk]
    while frontier:
        children = list(
            Folder.objects.filter(parent_id__in=frontier).values_list("id", flat=True)
        )
        new = [c for c in children if c not in ids]
        ids.update(new)
        frontier = new
    return ids


def _folder_path_map(user=None):
    """Map folder id → full path string ('A / B / C'), for labelling search hits.

    When `user` is given, restrict to folders the user can read."""
    return {f["id"]: f["path"] for f in _build_folder_flat(user=user)}


def _attach_thumbnails(files_list):
    """Annotate file record dicts in place with a thumb_url for image/PDF files."""

    def _is_thumbnailable(mime):
        mime = mime or ""
        return mime.startswith("image") or mime.endswith("pdf")

    thumb_ids = [r["id"] for r in files_list if _is_thumbnailable(r.get("mime"))]
    if not thumb_ids:
        return
    thumb_objs = {f.pk: f for f in File.objects.filter(pk__in=thumb_ids)}
    for record in files_list:
        if record["id"] not in thumb_objs:
            continue
        try:
            thumb = get_thumbnailer(thumb_objs[record["id"]].file).get_thumbnail(
                {"size": (32, 32), "crop": True, "quality": 85}
            )
            record["thumb_url"] = thumb.url
        except Exception:
            pass


def _folder_search_records(pk, q, user=None):
    """Recursively find files under folder pk (pk=0 = all folders) whose filename
    or indexed text content contains q. Returns OrdnerTabelle record dicts with
    an added 'pfad' key showing each file's folder path.

    When `user` is given, hits are restricted to readable folders."""
    from intern.fileindex import ensure_indexed

    if pk == 0:
        scope = File.objects.all()
    else:
        scope = File.objects.filter(folder_id__in=_descendant_folder_ids(pk))

    if user is not None:
        visible_ids = visible_folder_ids(user)
        scope = scope.filter(folder_id__in=visible_ids)

    ensure_indexed(scope)

    matched = scope.filter(
        Q(original_filename__icontains=q)
        | Q(name__icontains=q)
        | Q(suchindex__text__icontains=q)
    ).values(
        "id",
        "name",
        "original_filename",
        "owner_id",
        "folder_id",
        link=F("file"),
        besitzer=Concat(
            Coalesce("owner__first_name", Value("")),
            Value(" "),
            Coalesce("owner__last_name", Value("")),
        ),
        type=Value("File"),
        mime=F("mime_type"),
        size=F("_file_size"),
        created=F("uploaded_at"),
        modified=F("modified_at"),
    )
    files_list = list(matched)
    _attach_thumbnails(files_list)

    path_map = _folder_path_map(user=user)
    for record in files_list:
        record["pfad"] = path_map.get(record["folder_id"], "/")
        record["groesse"] = record.get("size") or 0
    return files_list


_FOLDER_PAGE_SIZE = 50


@login_required
def folder_view(request, pk):
    from .files import _get_file_extension

    original_pk = pk  # 0 means root; keep for URLs

    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0

    q = (request.GET.get("q") or "").strip()
    if len(q) >= 2:
        all_files = _folder_search_records(original_pk, q, user=request.user)
        page_items = all_files[offset : offset + _FOLDER_PAGE_SIZE + 1]
        has_more = len(page_items) > _FOLDER_PAGE_SIZE
        if has_more:
            page_items = page_items[:_FOLDER_PAGE_SIZE]
        table = OrdnerTabelle(page_items)
        RequestConfig(request, paginate=False).configure(table)
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            html = render_to_string("table_rows.html", {"table": table})
            return JsonResponse({
                "html": html,
                "has_more": has_more,
                "next_offset": offset + _FOLDER_PAGE_SIZE,
            })
        if original_pk == 0:
            breadcrumb = []
        else:
            breadcrumb = _folder_breadcrumb(Folder.objects.get(pk=original_pk), user=request.user)
        path_str = " / ".join(c["name"] for c in breadcrumb) if breadcrumb else "/"
        return render(
            request,
            "table.html",
            {
                "seitentitel": f"Suche in {path_str}: „{q}“",
                "topbar_icon": '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
                "breadcrumb": breadcrumb,
                "table": table,
                "current_pk": original_pk,
                "show_search": True,
                "search_query": q,
                "has_more": has_more,
                "next_offset": offset + _FOLDER_PAGE_SIZE,
            },
        )

    folder_up = []
    if pk == 0:
        pk = None
        current = None
        parent = None
        name = "/"
        breadcrumb = []
    else:
        current = Folder.objects.get(pk=pk)
        if not is_folder_visible(request.user, current):
            raise Http404
        parent = current.parent
        breadcrumb = _folder_breadcrumb(current, user=request.user)
        if current is not None:
            folder_up = [
                {
                    "id": parent.id if parent else 0,
                    "original_name": parent.name if parent else "/",
                    "name": "..",
                    "type": "Folder",
                    "besitzer": (
                        (parent.owner.first_name + " " + parent.owner.last_name)
                        if parent and parent.owner
                        else ""
                    ),
                    "created": parent.created_at if parent else None,
                    "modified": parent.modified_at if parent else None,
                }
            ]
        name = current.name

    folderfiles = (
        File.objects.filter(folder=OuterRef("pk"))
        .values("folder")
        .annotate(
            total_size=Sum("_file_size"),
            file_count=Count("id"),
        )
    )
    visible_ids = visible_folder_ids(request.user)
    folders_qs = (
        Folder.objects.filter(parent_id=pk, id__in=visible_ids)
        .values(
            "id",
            "name",
            "owner_id",
            besitzer=Concat(
                Coalesce("owner__first_name", Value("")),
                Value(" "),
                Coalesce("owner__last_name", Value("")),
            ),
            type=Value("Folder"),
            created=F("created_at"),
            modified=F("modified_at"),
        )
        .annotate(
            size=Coalesce(
                Subquery(folderfiles.values("total_size"), output_field=IntegerField()),
                0,
            ),
            count=Coalesce(
                Subquery(folderfiles.values("file_count"), output_field=IntegerField()),
                0,
            ),
        )
    )
    files = File.objects.filter(folder_id=pk).values(
        "id",
        "name",
        "original_filename",
        "owner_id",
        link=F("file"),
        besitzer=Concat(
            Coalesce("owner__first_name", Value("")),
            Value(" "),
            Coalesce("owner__last_name", Value("")),
        ),
        type=Value("File"),
        mime=F("mime_type"),
        size=F("_file_size"),
        created=F("uploaded_at"),
        modified=F("modified_at"),
    )
    files_list = list(files)
    for record in files_list:
        record["groesse"] = record.get("size") or 0

    def _is_thumbnailable(mime):
        mime = mime or ""
        return mime.startswith("image") or mime.endswith("pdf")

    thumb_ids = [r["id"] for r in files_list if _is_thumbnailable(r.get("mime"))]
    if thumb_ids:
        thumb_objs = {f.pk: f for f in File.objects.filter(pk__in=thumb_ids)}
        for record in files_list:
            if record["id"] not in thumb_objs:
                continue
            try:
                thumb = get_thumbnailer(thumb_objs[record["id"]].file).get_thumbnail(
                    {"size": (32, 32), "crop": True, "quality": 85}
                )
                record["thumb_url"] = thumb.url
            except Exception:
                pass

    folders_list = list(folders_qs)
    for record in folders_list:
        desc_ids = _descendant_folder_ids(record["id"])
        agg = File.objects.filter(folder_id__in=desc_ids).aggregate(
            s=Sum("_file_size"), c=Count("id")
        )
        record["groesse"] = agg["s"] or 0
        record["count"] = agg["c"] or 0
    for record in folder_up:
        record["groesse"] = None

    # Paginate folders + files; folder_up (..) is fixed and always shown on offset=0
    paginatable = folders_list + files_list
    page_items = paginatable[offset : offset + _FOLDER_PAGE_SIZE + 1]
    has_more = len(page_items) > _FOLDER_PAGE_SIZE
    if has_more:
        page_items = page_items[:_FOLDER_PAGE_SIZE]
    display_items = (folder_up if offset == 0 else []) + page_items

    table = OrdnerTabelle(display_items)
    table.columns.hide("pfad")
    RequestConfig(request, paginate=False).configure(table)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        html = render_to_string("table_rows.html", {"table": table})
        return JsonResponse({
            "html": html,
            "has_more": has_more,
            "next_offset": offset + _FOLDER_PAGE_SIZE,
        })

    path_str = " / ".join(c["name"] for c in breadcrumb) if breadcrumb else "/"
    permissions_url = None
    if current is not None and (
        request.user.is_superuser
        or request.user.has_perm("intern.manage_folder_permissions")
    ):
        from django.urls import reverse
        permissions_url = reverse("folder_permissions", args=[current.pk])

    return render(
        request,
        "table.html",
        {
            "seitentitel": f"Ordner: {path_str}",
            "topbar_icon": '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
            "breadcrumb": breadcrumb,
            "upload_folder_id": pk,
            "table": table,
            "show_file_actions": True,
            "new_folder_pk": original_pk,
            "current_pk": original_pk,
            "all_folders_flat": _build_folder_flat(user=request.user),
            "show_search": True,
            "search_query": "",
            "has_more": has_more,
            "next_offset": offset + _FOLDER_PAGE_SIZE,
            "permissions_url": permissions_url,
        },
    )


@login_required
@require_POST
def folder_create(request, pk):
    parent = Folder.objects.filter(pk=pk).first() if pk != 0 else None
    if pk != 0 and parent is None:
        raise Http404
    if pk != 0 and not is_folder_visible(request.user, parent):
        raise Http404
    _, can_write, _ = folder_access(request.user, parent)
    if not can_write and not request.user.has_perm("filer.add_folder"):
        raise PermissionDenied

    name = request.POST.get("name", "").strip()
    if name:
        new_folder = Folder.objects.create(
            name=name,
            parent_id=pk if pk != 0 else None,
            owner=request.user,
        )
        # Copy parent's FolderPermission rows to the new subfolder
        if parent is not None:
            FolderPermission.objects.bulk_create([
                FolderPermission(
                    folder=new_folder,
                    group_id=p.group_id,
                    can_read=p.can_read,
                    can_write=p.can_write,
                    can_delete=p.can_delete,
                )
                for p in FolderPermission.objects.filter(folder=parent)
            ])
        folders.invalidate()
    return redirect("folder_view", pk=pk)


@login_required
@require_POST
def folder_delete(request):
    referer_pk = int(request.POST.get("referer_pk", 0))
    can_delete_folder = request.user.has_perm("filer.delete_folder")
    for item_type, item_id in _parse_items(request.POST):
        if item_type == "Folder":
            # Folder deletion needs Layer 1 only
            if not can_delete_folder:
                continue
            try:
                _delete_folder_deep(Folder.objects.get(pk=item_id))
            except Folder.DoesNotExist:
                pass
        else:
            # File deletion needs can_delete on containing folder
            try:
                f = File.objects.get(pk=item_id)
            except File.DoesNotExist:
                continue
            _, _, can_del = folder_access(request.user, f.folder)
            if not can_del:
                continue
            f.delete()
    folders.invalidate()
    return redirect("folder_view", pk=referer_pk)


@permission_required("filer.change_folder", raise_exception=True)
@require_POST
def folder_move(request):
    referer_pk = int(request.POST.get("referer_pk", 0))
    raw_target = request.POST.get("target_pk", "")
    target_id = int(raw_target) if raw_target and raw_target != "0" else None
    target = Folder.objects.filter(pk=target_id).first() if target_id else None
    _, target_write, _ = folder_access(request.user, target)
    if not target_write:
        raise PermissionDenied
    for item_type, item_id in _parse_items(request.POST):
        if item_type == "Folder":
            Folder.objects.filter(pk=item_id).update(parent_id=target_id)
        else:
            try:
                f = File.objects.get(pk=item_id)
            except File.DoesNotExist:
                continue
            _, src_write, _ = folder_access(request.user, f.folder)
            if not src_write:
                continue
            File.objects.filter(pk=item_id).update(folder_id=target_id)
    return redirect("folder_view", pk=referer_pk)


@permission_required("filer.change_folder", raise_exception=True)
@require_POST
def folder_copy(request):
    referer_pk = int(request.POST.get("referer_pk", 0))
    raw_target = request.POST.get("target_pk", "")
    target_id = int(raw_target) if raw_target and raw_target != "0" else None
    target = Folder.objects.filter(pk=target_id).first() if target_id else None
    _, target_write, _ = folder_access(request.user, target)
    if not target_write:
        raise PermissionDenied
    for item_type, item_id in _parse_items(request.POST):
        if item_type == "Folder":
            try:
                src = Folder.objects.get(pk=item_id)
            except Folder.DoesNotExist:
                continue
            if _is_descendant_or_self(target_id, src.pk):
                continue
            _copy_folder_deep(src, target_id, request.user)
        elif item_type == "File":
            try:
                f = File.objects.get(pk=item_id)
            except File.DoesNotExist:
                continue
            File.objects.create(
                file=f.file,
                original_filename=f.original_filename,
                name=f.name,
                owner=request.user,
                folder_id=target_id,
                mime_type=f.mime_type,
            )
    folders.invalidate()
    return redirect("folder_view", pk=referer_pk)


@permission_required("filer.change_folder", raise_exception=True)
@require_POST
def folder_rename(request):
    item_type = request.POST.get("type", "")
    raw_id = request.POST.get("id", "")
    new_name = _validate_rename(request.POST.get("name", ""))
    if not new_name or not raw_id.isdigit():
        return JsonResponse({"status": "error", "message": "Ungültiger Name."}, status=400)
    item_id = int(raw_id)
    if item_type == "Folder":
        folder = get_object_or_404(Folder, pk=item_id)
        _, can_write, _ = folder_access(request.user, folder)
        if not can_write:
            raise PermissionDenied
        if Folder.objects.filter(parent_id=folder.parent_id, name=new_name).exclude(pk=item_id).exists():
            return JsonResponse({"status": "error", "message": "Name bereits vergeben."}, status=400)
        folder.name = new_name
        folder.save(update_fields=["name"])
        folders.invalidate()
    elif item_type == "File":
        f = get_object_or_404(File, pk=item_id)
        _, can_write, _ = folder_access(request.user, f.folder)
        if not can_write:
            raise PermissionDenied
        f.original_filename = new_name
        f.name = new_name
        f.save(update_fields=["original_filename", "name"])
    else:
        return JsonResponse({"status": "error", "message": "Unbekannter Typ."}, status=400)
    return JsonResponse({"status": "ok", "name": new_name})


@login_required
def folder_zip_download(request, pk):
    folder = get_object_or_404(Folder, pk=pk)
    if not is_folder_visible(request.user, folder):
        raise Http404

    def generator():
        buf = _ZipBuffer()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for arcname, f in _iter_folder_tree(folder):
                try:
                    with f.file.open("rb") as src:
                        data = src.read()
                except Exception:
                    continue
                zf.writestr(arcname, data)
                chunk = buf.drain()
                if chunk:
                    yield chunk
        tail = buf.drain()
        if tail:
            yield tail

    safe_name = (folder.name or f"ordner-{pk}").replace('"', "")
    response = StreamingHttpResponse(generator(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{safe_name}.zip"'
    return response