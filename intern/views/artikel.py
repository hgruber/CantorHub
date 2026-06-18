import difflib

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db.models import OuterRef, Subquery
from django.db.models.functions import Length
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.timezone import now
from django_tables2 import RequestConfig

from intern import folders
from intern.replacements import apply_replacements

from ..models import Artikel, ArtikelPermission
from ..tables import ArtikelTabelle

__all__ = [
    "article_list",
    "article_edit",
    "article_view",
    "article_history",
    "article_diff",
    "article_search",
    "article_permissions",
    "article_delete",
    "dummy",
]


def _artikel_access(user, artikel_name):
    """Returns (can_read, can_edit).

    No ArtikelPermission rows → True, True (open wiki default).
    No row with can_read=True → read is open to everyone.
    No row with can_edit=True → edit is open to everyone.
    Otherwise: user must be in a group with the respective flag.
    """
    perms = ArtikelPermission.objects.filter(artikel_name=artikel_name)
    if not perms.exists():
        return True, True
    read_restricted = perms.filter(can_read=True).exists()
    edit_restricted = perms.filter(can_edit=True).exists()
    gids = user.groups.values_list("id", flat=True)
    up = perms.filter(group_id__in=gids)
    can_read = not read_restricted or up.filter(can_read=True).exists()
    can_edit = not edit_restricted or up.filter(can_edit=True).exists()
    return can_read, can_edit


@login_required
def article_list(request):
    latest_id = (
        Artikel.objects.filter(name=OuterRef("name"))
        .order_by("-version")
        .values("id")[:1]
    )
    artikel = (
        Artikel.objects.filter(id=Subquery(latest_id))
        .select_related("autor")
        .annotate(size=Length("text"))
    )

    # Filter out articles where reading is restricted to groups the user isn't in
    restricted_names = set(
        ArtikelPermission.objects.filter(can_read=True)
        .values_list("artikel_name", flat=True)
        .distinct()
    )
    if request.user.has_perm("intern.manage_artikel_permissions"):
        readable_restricted = restricted_names
    else:
        gids = request.user.groups.values_list("id", flat=True)
        readable_restricted = set(
            ArtikelPermission.objects.filter(group_id__in=gids, can_read=True)
            .values_list("artikel_name", flat=True)
        )
    unreadable = restricted_names - readable_restricted
    artikel = artikel.exclude(name__in=unreadable)

    table = ArtikelTabelle(artikel)
    RequestConfig(request, paginate=False).configure(table)
    context = {
        "seitentitel": "Alle Artikel",
        "topbar_icon": '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
        "table": table,
        "upload_folder_id": folders.artikel(),
        "upload_folder_name": "Artikel",
    }
    return render(request, "table.html", context)


@login_required
def article_search(request):
    """Autocomplete for [[Artikel-Links]] in the wiki editor — distinct article
    names starting with the query."""
    q = request.GET.get("q", "")
    if not q:
        return JsonResponse([], safe=False)
    names = (
        Artikel.objects.filter(name__istartswith=q)
        .order_by("name")
        .values_list("name", flat=True)
        .distinct()[:20]
    )
    return JsonResponse([{"name": n} for n in names], safe=False)


@login_required
def article_edit(request, name):
    artikel = Artikel.objects.filter(name=name).order_by("-id").first()

    # If the article already exists, check edit permission
    if artikel is not None:
        _can_read, can_edit = _artikel_access(request.user, name)
        if not can_edit:
            raise PermissionDenied

    if request.method == "POST":
        text = request.POST.get("text", "")
        kommentar = request.POST.get("kommentar", "")
        next_version = (artikel.version + 1) if artikel else 1
        Artikel.objects.create(
            name=name,
            version=next_version,
            datum=now(),
            autor=request.user,
            kommentar=kommentar,
            text=text,
        )
        return redirect("article_view", name=name)

    context = {
        "artikel": artikel,
        "edit_text": artikel.text if artikel else "",
        "seitentitel": f"bearbeiten: {name}",
        "up": "article_list",
        "view": "article_view",
        "history": "article_history",
        "id": name,
        "back": "",
        "upload_folder_id": folders.artikel(),
        "upload_folder_name": "Artikel",
    }
    return render(request, "artikel.html", context)


@login_required
def article_view(request, name):
    latest = Artikel.objects.filter(name=name).order_by("-version").first()
    if not latest:
        return redirect(reverse("article_edit", args=[name]))

    can_read, can_edit = _artikel_access(request.user, name)
    if not can_read:
        raise PermissionDenied

    version_param = request.GET.get("version")
    if version_param:
        artikel = get_object_or_404(Artikel, name=name, version=version_param)
        is_outdated = artikel.version < latest.version
    else:
        artikel = latest
        is_outdated = False

    prev_version = None
    next_version = None
    if is_outdated:
        prev_version = (
            Artikel.objects.filter(name=name, version__lt=artikel.version)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        next_version = (
            Artikel.objects.filter(name=name, version__gt=artikel.version)
            .order_by("version")
            .values_list("version", flat=True)
            .first()
        )

    can_delete = request.user.has_perm("intern.delete_artikel")
    can_manage_perms = request.user.has_perm("intern.manage_artikel_permissions")

    context = {
        "artikel": artikel,
        "text": apply_replacements(artikel.text, request),
        "seitentitel": f"{artikel.name} (vom {artikel.datum.strftime('%-d.%-m.%Y')})"
        if is_outdated
        else artikel.name,
        "is_outdated": is_outdated,
        "latest_version": latest.version,
        "prev_version": prev_version,
        "next_version": next_version,
        "upload_folder_id": folders.artikel(),
        "upload_folder_name": "Artikel",
        "up": "article_list",
        "edit": "article_edit" if can_edit else None,
        "history": "article_history",
        "id": artikel.name,
        "can_delete": can_delete,
        "can_manage_perms": can_manage_perms,
    }
    return render(request, "artikel.html", context)


@login_required
def dummy(request, *args, **kwargs):
    context = {
        "seitentitel": "Nicht implementiert",
        "args": args,
        "kwargs": kwargs,
    }
    return render(request, "dummy.html", context)


_HISTORY_PAGE_SIZE = 25


def _history_rows(all_versions, offset):
    """Return (rows, has_more, next_offset) for one page of article history."""
    total = len(all_versions)
    end_idx = max(0, total - offset)
    # Fetch PAGE_SIZE items plus one extra predecessor for diff computation.
    start_idx = max(0, end_idx - _HISTORY_PAGE_SIZE - 1)
    slice_versions = all_versions[start_idx:end_idx]

    rows = []
    for i, v in enumerate(slice_versions):
        actual_idx = start_idx + i
        if actual_idx == 0:
            lines_added = len(v.text.splitlines())
            lines_removed = 0
        else:
            prev = slice_versions[i - 1]
            diff = list(difflib.unified_diff(
                prev.text.splitlines(), v.text.splitlines(), lineterm=""
            ))
            lines_added = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
            lines_removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
        if i == 0 and start_idx > 0:
            continue  # predecessor fetched for diff context only
        rows.append({"version": v, "lines_added": lines_added, "lines_removed": lines_removed})

    rows.reverse()
    next_offset = offset + len(rows)
    return rows, next_offset < total, next_offset


def article_history(request, name):
    can_read, can_edit = _artikel_access(request.user, name)
    if not can_read:
        raise PermissionDenied
    all_versions = list(Artikel.objects.filter(name=name).order_by("version"))
    if not all_versions:
        return redirect("article_list")

    total = len(all_versions)
    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0

    rows, has_more, next_offset = _history_rows(all_versions, offset)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        html = render_to_string(
            "_artikel_history_rows.html",
            {"rows": rows, "name": name, "total": total, "offset": offset},
            request=request,
        )
        return JsonResponse({"html": html, "has_more": has_more, "next_offset": next_offset})

    context = {
        "seitentitel": f"Versionen: {name}",
        "name": name,
        "rows": rows,
        "total": total,
        "offset": offset,
        "has_more": has_more,
        "next_offset": next_offset,
        "up": "article_list",
        "view": "article_view",
        "edit": "article_edit" if can_edit else None,
        "id": name,
    }
    return render(request, "artikel_history.html", context)


@login_required
def article_diff(request, name):
    can_read, can_edit = _artikel_access(request.user, name)
    if not can_read:
        raise PermissionDenied
    try:
        v1 = int(request.GET.get("v1", ""))
        v2 = int(request.GET.get("v2", ""))
    except (TypeError, ValueError):
        return redirect("article_history", name=name)

    if v1 > v2:
        v1, v2 = v2, v1

    old = get_object_or_404(Artikel, name=name, version=v1)
    new = get_object_or_404(Artikel, name=name, version=v2)

    old_lines = old.text.splitlines()
    new_lines = new.text.splitlines()

    mode = request.GET.get("mode", "unified")

    side_table = None
    if mode == "side":
        differ = difflib.HtmlDiff(wrapcolumn=80)
        side_table = differ.make_table(
            old_lines,
            new_lines,
            fromdesc=f"Version {v1} – {old.datum.strftime('%d.%m.%Y %H:%M')} ({old.autor})",
            todesc=f"Version {v2} – {new.datum.strftime('%d.%m.%Y %H:%M')} ({new.autor})",
            context=True,
            numlines=3,
        )

    unified_lines = []
    raw = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=3))
    for line in raw[2:]:  # skip --- / +++ header
        if line.startswith("@@"):
            unified_lines.append(("hunk", line))
        elif line.startswith("+"):
            unified_lines.append(("add", line[1:]))
        elif line.startswith("-"):
            unified_lines.append(("del", line[1:]))
        else:
            unified_lines.append(("ctx", line[1:] if line.startswith(" ") else line))

    context = {
        "seitentitel": f"Diff: {name} v{v1}→v{v2}",
        "name": name,
        "old": old,
        "new": new,
        "v1": v1,
        "v2": v2,
        "mode": mode,
        "side_table": side_table,
        "unified_lines": unified_lines,
        "up": "article_list",
        "view": "article_view",
        "edit": "article_edit" if can_edit else None,
        "history": "article_history",
        "id": name,
    }
    return render(request, "artikel_diff.html", context)


@login_required
def article_permissions(request, name):
    if not request.user.has_perm("intern.manage_artikel_permissions"):
        raise PermissionDenied

    if not Artikel.objects.filter(name=name).exists():
        raise Http404

    groups = Group.objects.all().order_by("name")
    existing = {
        ap.group_id: ap
        for ap in ArtikelPermission.objects.filter(artikel_name=name)
    }

    read_restricted = any(ap.can_read for ap in existing.values())
    edit_restricted = any(ap.can_edit for ap in existing.values())
    read_group_ids = {gid for gid, ap in existing.items() if ap.can_read}
    edit_group_ids = {gid for gid, ap in existing.items() if ap.can_edit}

    if request.method == "POST":
        read_mode = request.POST.get("read_mode")   # "all" or "restricted"
        edit_mode = request.POST.get("edit_mode")   # "all" or "restricted"
        read_groups = {int(x) for x in request.POST.getlist("read_groups")}
        edit_groups = {int(x) for x in request.POST.getlist("edit_groups")}

        ArtikelPermission.objects.filter(artikel_name=name).delete()

        if read_mode == "restricted" or edit_mode == "restricted":
            all_involved = read_groups | edit_groups
            for gid in all_involved:
                ArtikelPermission.objects.create(
                    artikel_name=name,
                    group_id=gid,
                    can_read=(read_mode == "restricted" and gid in read_groups),
                    can_edit=(edit_mode == "restricted" and gid in edit_groups),
                )

        return redirect("article_view", name=name)

    group_members = {
        g.id: [
            f"{u.first_name} {u.last_name}".strip() or u.username
            for u in g.user_set.filter(is_active=True).order_by("first_name", "last_name")
        ]
        for g in groups
    }
    return render(request, "artikel_berechtigungen.html", {
        "seitentitel": f"Berechtigungen: {name}",
        "artikel_name": name,
        "groups": groups,
        "read_restricted": read_restricted,
        "edit_restricted": edit_restricted,
        "read_group_ids": read_group_ids,
        "edit_group_ids": edit_group_ids,
        "group_members": group_members,
        "up": "article_list",
        "id": name,
    })


@login_required
def article_delete(request, name):
    if not request.user.has_perm("intern.delete_artikel"):
        raise PermissionDenied
    if request.method == "POST":
        Artikel.objects.filter(name=name).delete()
        ArtikelPermission.objects.filter(artikel_name=name).delete()
        return redirect("article_list")
    return redirect("article_view", name=name)
