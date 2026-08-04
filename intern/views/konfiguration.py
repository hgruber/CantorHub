import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..konfig_gruppen import gruppiere
from ..models import Konfiguration

__all__ = ["konfiguration"]


@login_required
def konfiguration(request):
    if not request.user.is_superuser:
        return redirect("article_list", name="Aktuell")

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

        for change in data.get("changes", []):
            try:
                obj = Konfiguration.objects.get(pk=int(change["id"]))
                obj.value = change.get("value", obj.value)
                obj.description = change.get("description", obj.description)
                obj.save(update_fields=["value", "description"])
            except (Konfiguration.DoesNotExist, KeyError, TypeError, ValueError):
                pass

        for new in data.get("new", []):
            key = (new.get("key") or "").strip()
            if key:
                Konfiguration.objects.update_or_create(
                    key=key,
                    defaults={
                        "value": new.get("value", ""),
                        "description": new.get("description", ""),
                    },
                )

        pk_list = [pk for pk in data.get("delete", []) if isinstance(pk, int)]
        if pk_list:
            Konfiguration.objects.filter(pk__in=pk_list).delete()

        return JsonResponse({"ok": True})

    rows = list(
        Konfiguration.objects.order_by("key").values("id", "key", "value", "description")
    )
    return render(request, "konfiguration.html", {
        "seitentitel": "Konfiguration",
        "gruppen": gruppiere(rows),
        "show_search": True,
    })
