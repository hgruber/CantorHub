from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django_tables2 import RequestConfig

from ..forms import OrtForm
from ..models import Ort
from ..tables import OrtTabelle

__all__ = [
    "ort_list",
    "ort_view",
    "ort_add",
    "ort_edit",
]


@login_required
def ort_list(request):
    orte = Ort.objects.order_by("name")
    table = OrtTabelle(orte)
    RequestConfig(request, paginate=False).configure(table)
    add = "ort_add" if request.user.has_perm("intern.add_ort") else None
    return render(request, "table.html", {
        "table": table,
        "seitentitel": "Orte",
        "topbar_icon": '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
        "add": add,
        "add_form": OrtForm() if request.user.has_perm("intern.add_ort") else None,
        "add_label": "Neuer Ort",
    })


@login_required
def ort_view(request, id):
    ort = get_object_or_404(Ort, id=id)
    context = {
        "seitentitel": ort.name,
        "ort": ort,
        "up": "ort_list",
        "edit": "ort_edit",
        "history": "ort_aenderungen" if request.user.has_perm("intern.change_ort") else None,
        "id": id,
    }
    return render(request, "ort_detail.html", context)


@permission_required("intern.add_ort", raise_exception=True)
def ort_add(request):
    if request.method == "POST":
        form = OrtForm(request.POST)
        if form.is_valid():
            ort = form.save()
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
    }
    return render(request, "ort_edit.html", context)