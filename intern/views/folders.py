import posixpath
import re
import unicodedata
import zipfile
from collections import defaultdict

from django.contrib.auth.decorators import login_required
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
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timezone import now
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig
from ._decorators import tabellenzustand
from ._pagination import ist_nachladen, nachlade_antwort, paginate_ordered, parse_offset

from easy_thumbnails.files import get_thumbnailer
from filer.models import File, Folder

from intern import dateiablage, folders
from intern.dateiablage import datei_loeschen
from intern.avatar_access import darf_avatar_aendern
from intern.folder_access import (
    folder_access,
    is_folder_visible,
    visible_folder_ids,
)
from intern.medientypen import AUDIO_ENDUNGEN

from ..models import Artikel, DateiVersion, FolderPermission
from ..tables import OrdnerTabelle

__all__ = [
    "folder_view",
    "folder_playlist",
    "folder_create",
    "folder_delete",
    "folder_move",
    "folder_link",
    "folder_duplicate",
    "folder_rename",
    "ablage_konflikte",
    "folder_zip_download",
    "folder_zip_selection",
]


def _sort_key(text):
    """Case- and accent-insensitive sort key ("Ärger" belongs next to "Arbeit")."""
    text = unicodedata.normalize("NFKD", text.casefold().replace("ß", "ss"))
    return "".join(c for c in text if not unicodedata.combining(c))


def _build_folder_flat(exclude_pk=None, user=None, ohne_backstage=False):
    """Return all folders as a flat list with full path strings, for the folder picker.

    The list is sorted by path segment, so parents precede their children and
    siblings appear alphabetically. When `user` is given, restrict the list to
    folders the user can read; `ohne_backstage` drops the Backstage branch,
    which only webmasters may target with a move, link or copy."""
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
    if ohne_backstage:
        gesperrt = _backstage_zweig()
        all_fldrs = [f for f in all_fldrs if f["id"] not in gesperrt]

    eintraege = [
        {"id": f["id"], "path": path_of(f)} for f in all_fldrs if f["id"] != exclude_pk
    ]
    eintraege.sort(key=lambda e: [_sort_key(teil) for teil in e["path"].split(" / ")])
    return eintraege


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
    """Recursively delete a folder and its contents, calling datei_loeschen() on
    each file so filer's custom delete() also removes the underlying blob from
    storage once no other folder links it."""
    for f in File.objects.filter(folder=folder).iterator():
        datei_loeschen(f)
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


def _perm_specs(folder):
    """FolderPermission rows of `folder` as plain (group_id, read, write, delete) tuples."""
    if folder is None:
        return []
    return [
        (p.group_id, p.can_read, p.can_write, p.can_delete)
        for p in FolderPermission.objects.filter(folder=folder)
    ]


def _apply_perm_specs(folder, specs):
    """Create FolderPermission rows on `folder` from `_perm_specs()` tuples."""
    FolderPermission.objects.bulk_create([
        FolderPermission(
            folder=folder,
            group_id=group_id,
            can_read=can_read,
            can_write=can_write,
            can_delete=can_delete,
        )
        for group_id, can_read, can_write, can_delete in specs
    ])


def _copy_folder_deep(src_folder, target_parent_id, owner, blob_kopieren=False):
    """Recursively copy a folder and its contents into target_parent_id.

    By default the files are *linked* (`dateiablage.verknuepfen`): new rows
    sharing the storage blob, filer's own copy semantics. With `blob_kopieren`
    they are truly duplicated instead (`dateiablage.kopieren`), yielding
    independent files. The new folder is empty, so the name rule only bites on
    a source folder that already holds a name twice.

    Each copied folder takes its source's own FolderPermission rows; what the
    source only inherited it inherits afresh from its new place (folder_access.py)."""
    new_name = _unique_folder_name(target_parent_id, src_folder.name)
    new_folder = Folder.objects.create(
        name=new_name, parent_id=target_parent_id, owner=owner
    )
    _apply_perm_specs(new_folder, _perm_specs(src_folder))
    for f in File.objects.filter(folder=src_folder):
        if blob_kopieren:
            dateiablage.kopieren(f, new_folder.pk, owner)
        else:
            dateiablage.verknuepfen(f, new_folder.pk, owner, {})
    for child in Folder.objects.filter(parent=src_folder):
        _copy_folder_deep(child, new_folder.pk, owner, blob_kopieren)
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


def _backstage_zweig():
    """Backstage and every folder below it — the portal files into them on its
    own, so only webmasters may target them with a move, link or copy."""
    backstage = folders.backstage()
    return _descendant_folder_ids(backstage) if backstage else set()


def _sieht_backstage(user):
    """The same question as the root listing in `folder_view`: who sees
    Backstage may also move, link or copy into it."""
    return user.has_perm("intern.manage_folder_permissions")


def _gesperrte_ziele(user):
    return set() if _sieht_backstage(user) else _backstage_zweig()


def _enthaelt_standardordner(pk):
    """The folder is, or holds, one of `folders.PFADE` — renaming, moving or
    deleting it would break the lookup, for everyone, superusers included."""
    return bool(_descendant_folder_ids(pk) & folders.standard_ids())


def _folder_path_map(user=None):
    """Map folder id → full path string ('A / B / C'), for labelling search hits.

    When `user` is given, restrict to folders the user can read."""
    return {f["id"]: f["path"] for f in _build_folder_flat(user=user)}


_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _attach_thumbnails(files_list):
    """Annotate file record dicts in place with a thumb_url for image/PDF files."""

    def _is_thumbnailable(mime):
        mime = mime or ""
        return mime.startswith("image") or mime.endswith("pdf") or mime == _DOCX_MIME

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
        scope = scope.filter(Q(folder_id__in=visible_ids) | Q(folder__isnull=True))

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

# Der Player im Kontextmenü ist ein <audio>-Element — nur was es spielen kann,
# darf angeboten werden. Der MIME-Typ ist die Hauptquelle; hochgeladene Dateien
# landen aber gelegentlich als application/octet-stream in filer, daher die
# Endungsliste als Rückfall. Sie ist mit dem Wiki-Player geteilt, siehe
# `intern/medientypen.py`.
_AUDIO_ENDUNGEN = AUDIO_ENDUNGEN


def _ist_audio(record):
    if (record.get("mime") or "").startswith("audio/"):
        return True
    name = (record.get("original_filename") or record.get("name") or "").lower()
    return name.endswith(_AUDIO_ENDUNGEN)


def _audio_filter():
    """Dasselbe Kriterium wie `_ist_audio()`, nur als Q für die Datenbank.

    Die beiden müssen dieselbe Menge treffen — sonst zählt die Ordnerzeile
    Dateien, die die Playlist danach nicht enthält. Sie stehen deshalb
    nebeneinander und lesen beide `_AUDIO_ENDUNGEN`. Auch die Rangfolge der
    Namensfelder muss stimmen: `_ist_audio()` sieht `name` nur an, wenn
    `original_filename` leer ist (es darf auch NULL sein)."""
    ohne_original = Q(original_filename__isnull=True) | Q(original_filename="")
    q = Q(mime_type__startswith="audio/")
    for endung in _AUDIO_ENDUNGEN:
        q |= Q(original_filename__iendswith=endung) | (
            ohne_original & Q(name__iendswith=endung)
        )
    return q


def _playlist_eintraege(records, ordnername):
    """Die Audios aus `records` als Warteschlange, wie der Mini-Player sie liest.

    `records` sind `values()`-Dicts mit `link`, `name`, `original_filename` und
    `mime` — dieselbe Form, die `folder_view` ohnehin baut."""
    return [
        {
            "url": f"/media/{r['link']}",
            "title": r.get("original_filename") or r.get("name") or "",
            "type": ordnername,
            "composer": "",
        }
        for r in records
        if r.get("link") and _ist_audio(r)
    ]


@login_required
@tabellenzustand
def folder_view(request, pk):
    from .files import _get_file_extension

    original_pk = pk  # 0 means root; keep for URLs

    offset = parse_offset(request)

    q = (request.GET.get("q") or "").strip()
    if len(q) >= 2:
        all_files = _folder_search_records(original_pk, q, user=request.user)
        probe = OrdnerTabelle(all_files)
        page_items, has_more = paginate_ordered(request, probe, offset, _FOLDER_PAGE_SIZE)
        table = OrdnerTabelle(page_items)
        RequestConfig(request, paginate=False).configure(table)
        if ist_nachladen(request):
            return nachlade_antwort("table_rows.html", {"table": table},
                                    has_more, offset + _FOLDER_PAGE_SIZE)
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
    # Backstage holds the folders the portal files into on its own. At the root
    # it is only listed for webmasters — hidden, not locked: the pages that use
    # those files and direct links keep working.
    if pk is None and not request.user.has_perm("intern.manage_folder_permissions"):
        visible_ids = visible_ids - {folders.backstage()}
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
    # `aktuell` ist der Pfad der laufenden Fassung — eine Zeile darin heisst,
    # dass diese Datei eine Versionshistorie hat.
    pfade = [r["link"] for r in files_list if r.get("link")]
    mit_versionen = set(
        DateiVersion.objects.filter(aktuell__in=pfade).values_list("aktuell", flat=True)
    ) if pfade else set()
    for record in files_list:
        record["groesse"] = record.get("size") or 0
        record["ist_audio"] = _ist_audio(record)
        record["hat_versionen"] = record.get("link") in mit_versionen

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
    if folders_list:
        # Größe und Elementzahl je Unterordner samt allem darunter. Früher war
        # das pro Zeile eine Breitensuche *und* eine Aggregation — bei fünf
        # Unterordnern elf Abfragen. Jetzt: einmal der Ordnerbaum, einmal die
        # Dateien, der Rest ist Rechnen.
        kinder = defaultdict(list)
        for kind_id, eltern_id in Folder.objects.values_list("id", "parent_id"):
            kinder[eltern_id].append(kind_id)
        je_ordner = {
            z["folder_id"]: (z["s"] or 0, z["c"])
            for z in File.objects.values("folder_id").annotate(
                s=Sum("_file_size"), c=Count("id")
            )
        }
        for record in folders_list:
            stapel = [record["id"]]
            gesehen = set()
            groesse = anzahl = 0
            while stapel:
                fid = stapel.pop()
                if fid in gesehen:
                    continue
                gesehen.add(fid)
                s, c = je_ordner.get(fid, (0, 0))
                groesse += s
                anzahl += c
                stapel.extend(kinder.get(fid, ()))
            record["groesse"] = groesse
            record["count"] = anzahl
    for record in folder_up:
        record["groesse"] = None

    # Womit das Kontextmenü einer Ordnerzeile etwas anfangen kann. Anders als
    # Größe und Elementzahl oben zählt das nur die direkt enthaltenen Dateien —
    # so weit reicht auch, was „alle abspielen"/„als Galerie" dann liefert.
    medien = {
        r["folder_id"]: r
        for r in File.objects.filter(folder_id__in=[r["id"] for r in folders_list])
        .values("folder_id")
        .annotate(
            audios=Count("id", filter=_audio_filter()),
            bilder=Count("id", filter=Q(mime_type__startswith="image/")),
        )
    }
    for record in folders_list:
        zaehler = medien.get(record["id"])
        record["audios"] = zaehler["audios"] if zaehler else 0
        record["bilder"] = zaehler["bilder"] if zaehler else 0

    # Sort the full datasets before pagination so ordering is correct across pages.
    # Folders always come first; the sort key is applied within each group separately.
    _ALLOWED_SORT_FIELDS = {"name", "besitzer", "created", "modified", "size", "type"}
    raw_sort = request.GET.get("sort", "name")
    if raw_sort.startswith("-"):
        sort_field, sort_reverse = raw_sort[1:], True
    else:
        sort_field, sort_reverse = raw_sort, False
    if sort_field not in _ALLOWED_SORT_FIELDS:
        sort_field, sort_reverse = "name", False

    def _sort_records(records):
        return sorted(
            records,
            key=lambda r: (r.get(sort_field) is None, r.get(sort_field) or ""),
            reverse=sort_reverse,
        )

    folders_list = _sort_records(folders_list)
    files_list = _sort_records(files_list)

    # Die Ordner-Playlist umfasst den ganzen Ordner, nicht nur die geladene
    # Seite — nach dem Sortieren gebaut, damit „der Reihe nach" die angezeigte
    # Reihenfolge ist.
    ordner_playlist = _playlist_eintraege(files_list, name)

    # Paginate folders + files; folder_up (..) is fixed and always shown on offset=0
    paginatable = folders_list + files_list
    # `?datei=<pk>` (Sprung aus dem Datei-Menü eines Artikels): die erste Seite
    # reicht mindestens bis zu dieser Datei, damit das Skript sie anspringen kann.
    seite = _FOLDER_PAGE_SIZE
    gesucht = request.GET.get("datei", "")
    if offset == 0 and gesucht.isdigit():
        for i, r in enumerate(paginatable):
            if r.get("type") == "File" and r.get("id") == int(gesucht):
                seite = max(seite, i + 1)
                break
    page_items = paginatable[offset : offset + seite + 1]
    has_more = len(page_items) > seite
    if has_more:
        page_items = page_items[:seite]
    display_items = (folder_up if offset == 0 else []) + page_items

    table = OrdnerTabelle(display_items)
    table.columns.hide("pfad")
    RequestConfig(request, paginate=False).configure(table)

    if ist_nachladen(request):
        return nachlade_antwort("table_rows.html", {"table": table},
                                has_more, offset + _FOLDER_PAGE_SIZE)

    path_str = " / ".join(c["name"] for c in breadcrumb) if breadcrumb else "/"
    permissions_url = None
    if current is not None and request.user.has_perm("intern.manage_folder_permissions"):
        permissions_url = reverse("folder_permissions", args=[current.pk])

    _, can_write_here, can_delete_perm = folder_access(request.user, current)
    can_delete_here = can_delete_perm or request.user.has_perm("intern.delete_folder")

    has_images = current is not None and any(
        (r.get("mime") or "").startswith("image/") for r in files_list
    )
    gallery_url = reverse("gallerie_view", args=[original_pk]) if has_images else None

    return render(
        request,
        "table.html",
        {
            "seitentitel": f"Ordner: {path_str}",
            "topbar_icon": '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
            "breadcrumb": breadcrumb,
            "upload_folder_id": pk,
            "upload_folder_name": current.name if current else "",
            "table": table,
            "show_file_actions": True,
            "can_write_here": can_write_here,
            "can_delete_here": can_delete_here,
            "new_folder_pk": original_pk,
            "current_pk": original_pk,
            "all_folders_flat": _build_folder_flat(
                user=request.user, ohne_backstage=not _sieht_backstage(request.user)
            ),
            "gesperrte_ziele": ",".join(str(i) for i in sorted(_gesperrte_ziele(request.user))),
            "show_search": True,
            "search_query": "",
            "has_more": has_more,
            "next_offset": offset + seite,
            "permissions_url": permissions_url,
            "gallery_url": gallery_url,
            # Der geöffnete Ordner hat keine eigene Zeile und damit kein
            # Kontextmenü — für ihn übernimmt das Play-Menü der Topbar, das
            # seine Liste wie /intern/titel/ aus `playlists-data` holt.
            "play_menu": bool(ordner_playlist),
            "ordner_playlist_count": len(ordner_playlist),
            "playlists": {"ordner": ordner_playlist} if ordner_playlist else None,
        },
    )


@login_required
def folder_playlist(request, pk):
    """Die Audios eines Ordners als Warteschlange für den Mini-Player.

    Das Kontextmenü einer Ordnerzeile holt sie erst beim Klick — die Playlists
    aller sichtbaren Unterordner mitzurendern, blähte die Ordneransicht auf.
    Wie `gallerie_view` betrifft das nur die direkt enthaltenen Dateien, und die
    Reihenfolge ist die der unsortierten Ordneransicht (nach Name)."""
    folder = get_object_or_404(Folder, pk=pk)
    if not is_folder_visible(request.user, folder):
        raise Http404
    can_read, _, _ = folder_access(request.user, folder)
    if not can_read:
        raise Http404

    records = File.objects.filter(folder=folder).values(
        "name",
        "original_filename",
        link=F("file"),
        mime=F("mime_type"),
    )
    geordnet = sorted(records, key=lambda r: (r.get("name") is None, r.get("name") or ""))
    return JsonResponse({"items": _playlist_eintraege(geordnet, folder.name)})


@login_required
@require_POST
def folder_create(request, pk):
    parent = Folder.objects.filter(pk=pk).first() if pk != 0 else None
    if pk != 0 and parent is None:
        raise Http404
    if pk != 0 and not is_folder_visible(request.user, parent):
        raise Http404
    _, can_write, _ = folder_access(request.user, parent)
    if not can_write:
        raise PermissionDenied

    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    name = request.POST.get("name", "").strip()

    if not name:
        if is_ajax:
            return JsonResponse({"error": "Name darf nicht leer sein."}, status=400)
        return redirect("folder_view", pk=pk)
    if not dateiablage.ordnername_frei(pk if pk != 0 else None, name):
        if is_ajax:
            return JsonResponse({"error": "Einen Ordner dieses Namens gibt es hier schon."}, status=400)
        return redirect("folder_view", pk=pk)

    new_folder = Folder.objects.create(
        name=name,
        parent_id=pk if pk != 0 else None,
        owner=request.user,
    )
    folders.invalidate()

    if is_ajax:
        row_data = {
            "id": new_folder.pk,
            "name": name,
            "type": "Folder",
            "besitzer": f"{request.user.first_name} {request.user.last_name}",
            "created": new_folder.created_at,
            "modified": new_folder.modified_at,
            "size": 0,
            "groesse": 0,
            "count": 0,
        }
        table = OrdnerTabelle([row_data])
        table.columns.hide("pfad")
        RequestConfig(request, paginate=False).configure(table)
        html = render_to_string("table_rows.html", {"table": table})
        return JsonResponse({"html": html, "pk": new_folder.pk, "name": name})

    return redirect("folder_view", pk=pk)


@login_required
@require_POST
def folder_delete(request):
    referer_pk = int(request.POST.get("referer_pk", 0))
    global_delete = request.user.has_perm("intern.delete_folder")
    for item_type, item_id in _parse_items(request.POST):
        if item_type == "Folder":
            try:
                folder = Folder.objects.get(pk=item_id)
            except Folder.DoesNotExist:
                continue
            _, _, can_del = folder_access(request.user, folder)
            if not (global_delete or can_del):
                continue
            if _enthaelt_standardordner(folder.pk):
                continue
            _delete_folder_deep(folder)
        else:
            try:
                f = File.objects.get(pk=item_id)
            except File.DoesNotExist:
                continue
            _, _, can_del = folder_access(request.user, f.folder)
            if not (global_delete or can_del):
                continue
            if not darf_avatar_aendern(request.user, f):
                continue
            datei_loeschen(f)
    folders.invalidate()
    return redirect("folder_view", pk=referer_pk)


@login_required
@require_POST
def folder_move(request):
    referer_pk = int(request.POST.get("referer_pk", 0))
    raw_target = request.POST.get("target_pk", "")
    target_id = int(raw_target) if raw_target and raw_target != "0" else None
    target = Folder.objects.filter(pk=target_id).first() if target_id else None
    _, target_write, _ = folder_access(request.user, target)
    if not target_write or target_id in _gesperrte_ziele(request.user):
        raise PermissionDenied
    entscheidungen = dateiablage.entscheidungen_lesen(request.POST.getlist("entscheidung"))
    for item_type, item_id in _parse_items(request.POST):
        if item_type == "Folder":
            folder = Folder.objects.filter(pk=item_id).first()
            if folder is None:
                continue
            # In sich selbst oder einen eigenen Unterordner: der Zweig hinge
            # danach an sich selbst und wäre von der Wurzel aus unerreichbar.
            if _is_descendant_or_self(target_id, folder.pk):
                continue
            # Standardordner bleiben, wo das Portal sie sucht.
            if _enthaelt_standardordner(folder.pk):
                continue
            # Ein Name, ein Ordner: was dort schon so heißt, bleibt, wo es ist.
            if not dateiablage.ordnername_frei(target_id, folder.name, folder.pk):
                continue
            Folder.objects.filter(pk=item_id).update(parent_id=target_id)
        else:
            try:
                f = File.objects.get(pk=item_id)
            except File.DoesNotExist:
                continue
            _, src_write, _ = folder_access(request.user, f.folder)
            if not src_write:
                continue
            if not darf_avatar_aendern(request.user, f):
                continue
            dateiablage.verschieben(f, target_id, request.user, entscheidungen)
    folders.invalidate()
    return redirect("folder_view", pk=referer_pk)


def _copy_action(request, blob_kopieren):
    """Shared body of folder_link and folder_duplicate — same selection, same
    permission checks, they differ only in whether the blob is shared or copied."""
    referer_pk = int(request.POST.get("referer_pk", 0))
    raw_target = request.POST.get("target_pk", "")
    target_id = int(raw_target) if raw_target and raw_target != "0" else None
    target = Folder.objects.filter(pk=target_id).first() if target_id else None
    _, target_write, _ = folder_access(request.user, target)
    if not target_write or target_id in _gesperrte_ziele(request.user):
        raise PermissionDenied
    entscheidungen = dateiablage.entscheidungen_lesen(request.POST.getlist("entscheidung"))
    for item_type, item_id in _parse_items(request.POST):
        if item_type == "Folder":
            try:
                src = Folder.objects.get(pk=item_id)
            except Folder.DoesNotExist:
                continue
            if _is_descendant_or_self(target_id, src.pk):
                continue
            src_read, _, _ = folder_access(request.user, src)
            if not src_read:
                continue
            _copy_folder_deep(src, target_id, request.user, blob_kopieren)
        elif item_type == "File":
            try:
                f = File.objects.get(pk=item_id)
            except File.DoesNotExist:
                continue
            src_read, _, _ = folder_access(request.user, f.folder)
            if not src_read:
                continue
            if blob_kopieren:
                dateiablage.kopieren(f, target_id, request.user)
            else:
                dateiablage.verknuepfen(f, target_id, request.user, entscheidungen)
    folders.invalidate()
    # Das Datei-Menü im Artikel verknüpft von dort aus und will dorthin zurück.
    ziel = request.POST.get("next", "")
    if ziel and url_has_allowed_host_and_scheme(
        ziel, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(ziel)
    return redirect("folder_view", pk=referer_pk)


@login_required
@require_POST
def ablage_konflikte(request):
    """Die Vorabprüfung zu Verschieben, Referenz und Kopieren: welche Dateien
    der Auswahl im Zielordner auf einen vergebenen Namen treffen, und was zur
    Wahl steht. Der Dialog fragt danach, die Aktion selbst prüft erneut und
    überspringt, wofür keine Wahl mitkommt (dateiablage.OPTIONEN)."""
    aktion = request.POST.get("aktion", "")
    if aktion not in ("verschieben", "verknuepfen", "kopieren"):
        return JsonResponse({"status": "error", "message": "Unbekannte Aktion."}, status=400)
    raw_target = request.POST.get("target_pk", "")
    target_id = int(raw_target) if raw_target.isdigit() and raw_target != "0" else None
    konflikte = []
    for item_type, item_id in _parse_items(request.POST):
        if item_type == "Folder":
            folder = Folder.objects.filter(pk=item_id).first()
            if folder is None:
                continue
            # Kopieren überspringt das Ziel im eigenen Zweig genauso (_copy_action).
            if _is_descendant_or_self(target_id, folder.pk):
                art = "in_sich_selbst"
            elif aktion == "verschieben" and not dateiablage.ordnername_frei(
                    target_id, folder.name, folder.pk):
                art = "ordnername"
            else:
                continue
            konflikte.append({
                "schluessel": f"Folder:{folder.pk}",
                "datei": folder.name,
                "ordner": dateiablage.ordner_pfad(Folder.objects.filter(pk=target_id).first()),
                "art": art,
                "optionen": [],
            })
            continue
        f = File.objects.filter(pk=item_id).select_related("folder").first()
        if f is None:
            continue
        konflikt = dateiablage.pruefen(aktion, f, target_id, request.user)
        if konflikt is not None:
            konflikte.append(konflikt.als_json())
    return JsonResponse({"konflikte": konflikte})


@login_required
@require_POST
def folder_link(request):
    """Link the selection into another folder — same file, second place.
    An update to the file later shows up in every folder it is linked into."""
    return _copy_action(request, blob_kopieren=False)


@login_required
@require_POST
def folder_duplicate(request):
    """Duplicate the selection into another folder — independent copies whose
    contents can diverge from the original."""
    return _copy_action(request, blob_kopieren=True)


def _wiki_links_umschreiben(alter_name, neuer_name, user):
    """Point [[Datei:…]] links at the renamed file, in every article that has one.

    Articles are immutable versions, so this writes a *new* version per article
    (same way as article_edit) — the change shows up in the article history and
    can be diffed or rolled back. Articles the user may not edit are left alone
    and reported back. Returns (angepasste Artikel, übersprungene Artikel)."""
    from .artikel import _artikel_access

    betroffen = Artikel.aktuelle_datei_verweise().get(alter_name, [])
    angepasst, uebersprungen = [], []

    def ersetze(match):
        if Artikel.dateiname_aus_link(match.group(1)) != alter_name:
            return match.group(0)
        rest = match.group(2) or ""
        return f"[[Datei:{neuer_name}{rest}]]"

    for artikel_name in betroffen:
        _, can_edit = _artikel_access(user, artikel_name)
        if not can_edit:
            uebersprungen.append(artikel_name)
            continue
        letzte = Artikel.objects.filter(name=artikel_name).order_by("-version").first()
        if letzte is None:
            continue
        neuer_text = re.sub(
            r"\[\[Datei:([^|\]]+)(\|[^\]]+)?\]\]", ersetze, letzte.text
        )
        if neuer_text == letzte.text:
            continue
        Artikel.objects.create(
            name=artikel_name,
            version=letzte.version + 1,
            datum=now(),
            autor=user if user and user.is_authenticated else None,
            kommentar=f"Dateiname geändert: {alter_name} → {neuer_name}",
            text=neuer_text,
        )
        angepasst.append(artikel_name)
    return angepasst, uebersprungen


@login_required
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
        if folder.pk in folders.standard_ids():
            return JsonResponse(
                {"status": "error", "message": "Standardordner lassen sich nicht umbenennen."},
                status=400,
            )
        if not dateiablage.ordnername_frei(folder.parent_id, new_name, folder.pk):
            return JsonResponse({"status": "error", "message": "Name bereits vergeben."}, status=400)
        folder.name = new_name
        folder.save(update_fields=["name"])
        folders.invalidate()
    elif item_type == "File":
        f = get_object_or_404(File, pk=item_id)
        _, can_write, _ = folder_access(request.user, f.folder)
        if not can_write:
            raise PermissionDenied
        if not darf_avatar_aendern(request.user, f):
            raise PermissionDenied
        alter_name = f.original_filename or f.name
        # One file, one name — a rename reaches every folder it is linked into.
        # Where the new name is taken, the file becomes a revision of the file
        # holding it — once the dialog has a choice for each of those folders.
        status, konflikte = dateiablage.umbenennen(
            f, new_name, request.user,
            dateiablage.entscheidungen_lesen(request.POST.getlist("entscheidung")),
        )
        if status == "offen":
            return JsonResponse(
                {"status": "konflikt", "konflikte": [k.als_json() for k in konflikte]},
                status=409,
            )
        if status == "gesperrt":
            gesperrt = next(k for k in konflikte if k.art == dateiablage.ART_GESPERRT)
            return JsonResponse({
                "status": "error",
                "message": f"„{new_name}“ gibt es schon in {dateiablage.ordner_pfad(gesperrt.ziel.folder)}"
                           " — diese Datei darfst du nicht ändern.",
            }, status=403)
        if status == "abgebrochen":
            return JsonResponse({"status": "abgebrochen", "name": alter_name})
        if request.POST.get("links_mitziehen"):
            angepasst, uebersprungen = _wiki_links_umschreiben(
                alter_name, new_name, request.user
            )
            return JsonResponse({
                "status": "ok",
                "name": new_name,
                "verschmolzen": bool(konflikte),
                "links_angepasst": angepasst,
                "links_uebersprungen": uebersprungen,
            })
        # Verschmolzen: die Zeile kann in einer anderen aufgegangen sein — die
        # Liste lädt dann neu, statt nur den Namen zu tauschen.
        return JsonResponse({"status": "ok", "name": new_name, "verschmolzen": bool(konflikte)})
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


@login_required
@require_POST
def folder_zip_selection(request):
    """Stream a ZIP archive containing all selected folders and files."""
    items = list(_parse_items(request.POST))
    if not items:
        return JsonResponse({"error": "Keine Elemente ausgewählt."}, status=400)

    def generator():
        buf = _ZipBuffer()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for item_type, item_id in items:
                if item_type == "Folder":
                    try:
                        folder = Folder.objects.get(pk=item_id)
                    except Folder.DoesNotExist:
                        continue
                    if not is_folder_visible(request.user, folder):
                        continue
                    for arcname, f in _iter_folder_tree(folder, prefix=folder.name):
                        try:
                            with f.file.open("rb") as src:
                                data = src.read()
                        except Exception:
                            continue
                        zf.writestr(arcname, data)
                        chunk = buf.drain()
                        if chunk:
                            yield chunk
                elif item_type == "File":
                    try:
                        f = File.objects.get(pk=item_id)
                    except File.DoesNotExist:
                        continue
                    can_read, _, _ = folder_access(request.user, f.folder)
                    if not can_read:
                        continue
                    try:
                        with f.file.open("rb") as src:
                            data = src.read()
                    except Exception:
                        continue
                    arcname = f.original_filename or f.name or f"datei-{f.pk}"
                    zf.writestr(arcname, data)
                    chunk = buf.drain()
                    if chunk:
                        yield chunk
        tail = buf.drain()
        if tail:
            yield tail

    response = StreamingHttpResponse(generator(), content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="auswahl.zip"'
    return response