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
        return redirect("article_view", name="Aktuell")

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
                obj._audit_user = request.user
                obj.save(update_fields=["value", "description"])
            except (Konfiguration.DoesNotExist, KeyError, TypeError, ValueError):
                pass

        for new in data.get("new", []):
            key = (new.get("key") or "").strip()
            if key:
                # Kein update_or_create: das würde intern speichern, bevor wir
                # _audit_user auf der Instanz setzen können, und der Signal-Handler
                # würde den Änderungsprotokoll-Eintrag ohne Benutzer schreiben.
                obj = Konfiguration.objects.filter(key=key).first() or Konfiguration(key=key)
                obj.value = new.get("value", "")
                obj.description = new.get("description", "")
                obj._audit_user = request.user
                obj.save()

        pk_list = [pk for pk in data.get("delete", []) if isinstance(pk, int)]
        for obj in Konfiguration.objects.filter(pk__in=pk_list):
            obj._audit_user = request.user
            obj.delete()

        return JsonResponse({"ok": True})

    rows = list(
        Konfiguration.objects.order_by("key").values("id", "key", "value", "description")
    )
    return render(request, "konfiguration.html", {
        "seitentitel": "Konfiguration",
        "gruppen": gruppiere(rows),
        "show_search": True,
    })
