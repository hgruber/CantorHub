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
            form.save()
            return redirect("ort_view", id=id)
    else:
        form = OrtForm(instance=ort)
    context = {
        "form": form,
        "seitentitel": f"bearbeiten: {ort.name}",
        "view": "ort_view",
        "id": id,
    }
    return render(request, "ort_edit.html", context)