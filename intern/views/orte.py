from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig

from ..forms import OrtForm
from ..models import Ort
from ..tables import OrtTabelle
from ._decorators import tabellenzustand
from ._pagination import ist_nachladen, nachlade_antwort, paginate_ordered, parse_offset

__all__ = [
    "ort_list",
    "ort_view",
    "ort_add",
    "ort_edit",
    "ort_delete",
]

_PAGE_SIZE = 50


@login_required
@tabellenzustand
def ort_list(request):
    qs = Ort.objects.order_by("name")

    offset = parse_offset(request)

    probe = OrtTabelle(qs)
    page, has_more = paginate_ordered(request, probe, offset, _PAGE_SIZE)
    table = OrtTabelle(page)
    RequestConfig(request, paginate=False).configure(table)

    if ist_nachladen(request):
        return nachlade_antwort("table_rows.html", {"table": table},
                                has_more, offset + _PAGE_SIZE)

    add = "ort_add" if request.user.has_perm("intern.add_ort") else None
    return render(request, "table.html", {
        "table": table,
        "seitentitel": "Orte",
        "topbar_icon": '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
        "add": add,
        "add_form": OrtForm() if request.user.has_perm("intern.add_ort") else None,
        "add_label": "Neuer Ort",
        "has_more": has_more,
        "next_offset": offset + _PAGE_SIZE,
    })


@login_required
def ort_view(request, id):
    ort = get_object_or_404(Ort, id=id)
    context = {
        "seitentitel": ort.name,
        "ort": ort,
        "up": "ort_list",
        "edit": "ort_edit" if request.user.has_perm("intern.change_ort") else None,
        "history": "ort_aenderungen" if request.user.has_perm("intern.change_ort") else None,
        "id": id,
    }
    return render(request, "ort_detail.html", context)


@permission_required("intern.add_ort", raise_exception=True)
def ort_add(request):
    if request.method == "POST":
        form = OrtForm(request.POST)
        if form.is_valid():
            ort = form.save(commit=False)
            ort._audit_user = request.user
            ort.save()
            return redirect("ort_view", id=ort.id)
    else:
        form = OrtForm()
    context = {
        "form": form,
        "seitentitel": "Neuer Ort",
    }
    return render(request, "ort_edit.html", context)


@permission_required("intern.change_ort", raise_exception=True)
def ort_edit(request, id):
    ort = get_object_or_404(Ort, id=id)
    if request.method == "POST":
        form = OrtForm(request.POST, instance=ort)
        if form.is_valid():
            instance = form.save(commit=False)
            instance._audit_user = request.user
            instance.save()
            form.save_m2m()
            return redirect("ort_view", id=id)
    else:
        form = OrtForm(instance=ort)
    context = {
        "form": form,
        "ort": ort,
        "seitentitel": f"bearbeiten: {ort.name}",
        "view": "ort_view",
        "id": id,
        "can_delete": request.user.has_perm("intern.delete_ort"),
    }
    return render(request, "ort_edit.html", context)


@permission_required("intern.delete_ort", raise_exception=True)
@require_POST
def ort_delete(request, id):
    ort = get_object_or_404(Ort, id=id)
    ort._audit_user = request.user
    ort.delete()
    return redirect("ort_list")