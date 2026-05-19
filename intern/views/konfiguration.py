from django.contrib.auth.decorators import login_required
from django.forms import modelformset_factory
from django.shortcuts import redirect, render

from ..forms import KonfigurationForm
from ..models import Konfiguration

__all__ = ["konfiguration"]


@login_required
def konfiguration(request):
    if not request.user.is_superuser:
        return redirect("article_list", name="Aktuell")

    KonfigurationFormSet = modelformset_factory(
        Konfiguration,
        form=KonfigurationForm,
        extra=1,
        can_delete=True,
    )

    if request.method == "POST":
        formset = KonfigurationFormSet(request.POST)
        if formset.is_valid():
            formset.save()
            return redirect("konfiguration")
    else:
        formset = KonfigurationFormSet()

    context = {
        "formset": formset,
        "seitentitel": "Konfiguration",
    }
    return render(request, "konfiguration.html", context)