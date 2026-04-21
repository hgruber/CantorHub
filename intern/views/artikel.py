import difflib

from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.timezone import now

from intern import folders
from intern.replacements import apply_replacements

from ..models import Artikel

__all__ = [
    "article_list",
    "article_edit",
    "article_view",
    "article_history",
    "article_diff",
    "dummy",
]


@login_required
def article_list(request):
    artikel = Artikel.objects.values_list("name", flat=True).distinct()
    context = {
        "seitentitel": "Alle Artikel",
        "artikel": artikel,
        "upload_folder_id": folders.artikel(),
    }
    return render(request, "wiki.html", context)


@permission_required("intern.change_artikel", raise_exception=True)
def article_edit(request, name):
    artikel = Artikel.objects.filter(name=name).order_by("-id").first()

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
    }
    return render(request, "artikel.html", context)


@login_required
def article_view(request, name):
    latest = Artikel.objects.filter(name=name).order_by("-version").first()
    if not latest:
        return redirect(reverse("article_edit", args=[name]))

    version_param = request.GET.get("version")
    if version_param:
        artikel = get_object_or_404(Artikel, name=name, version=version_param)
        is_outdated = artikel.version < latest.version
    else:
        artikel = latest
        is_outdated = False

    context = {
        "artikel": artikel,
        "text": apply_replacements(artikel.text, request),
        "seitentitel": f"{artikel.name} (vom {artikel.datum.strftime('%-d.%-m.%Y')})"
        if is_outdated
        else artikel.name,
        "is_outdated": is_outdated,
        "latest_version": latest.version,
        "upload_folder_id": folders.artikel(),
        "up": "article_list",
        "edit": "article_edit"
        if request.user.has_perm("intern.change_artikel")
        else None,
        "history": "article_history",
        "id": artikel.name,
    }
    return render(request, "artikel.html", context)


def dummy(request, *args, **kwargs):
    context = {
        "seitentitel": "Nicht implementiert",
        "args": args,
        "kwargs": kwargs,
    }
    return render(request, "dummy.html", context)


@login_required
def article_history(request, name):
    versions = list(Artikel.objects.filter(name=name).order_by("version"))
    if not versions:
        return redirect("article_list")

    rows = []
    for i, v in enumerate(versions):
        if i == 0:
            lines_added = len(v.text.splitlines())
            lines_removed = 0
        else:
            prev = versions[i - 1]
            diff = list(
                difflib.unified_diff(
                    prev.text.splitlines(), v.text.splitlines(), lineterm=""
                )
            )
            lines_added = sum(
                1 for l in diff if l.startswith("+") and not l.startswith("+++")
            )
            lines_removed = sum(
                1 for l in diff if l.startswith("-") and not l.startswith("---")
            )
        rows.append(
            {
                "version": v,
                "lines_added": lines_added,
                "lines_removed": lines_removed,
            }
        )
    rows.reverse()

    context = {
        "seitentitel": f"Versionen: {name}",
        "name": name,
        "rows": rows,
        "up": "article_list",
        "view": "article_view",
        "edit": "article_edit",
        "id": name,
    }
    return render(request, "artikel_history.html", context)


@login_required
def article_diff(request, name):
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
        "edit": "article_edit",
        "history": "article_history",
        "id": name,
    }
    return render(request, "artikel_diff.html", context)