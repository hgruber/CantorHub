import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Permission
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..models import User

__all__ = ["berechtigungen"]

PERMISSION_DEFS = [
    ("intern.change_artikel", "bearbeiten",   "Artikel"),
    ("intern.add_forum",      "erstellen",    "Forum"),
    ("filer.add_folder",      "verwalten",    "Dateien"),
    ("intern.add_ort",        "anlegen",      "Orte"),
    ("intern.change_ort",     "bearbeiten",   "Orte"),
    ("intern.add_termin",     "anlegen",      "Termine"),
    ("intern.change_termin",  "bearbeiten",   "Termine"),
    ("intern.delete_termin",  "löschen",      "Termine"),
    ("intern.change_zusage",  "Anwesenheit",  "Termine"),
    ("intern.add_lied",       "anlegen",      "Repertoire"),
    ("intern.change_lied",    "bearbeiten",   "Repertoire"),
    ("intern.delete_lied",    "löschen",      "Repertoire"),
    ("intern.add_user",       "anlegen",      "Mitglieder"),
]


@login_required
def berechtigungen(request):
    if not request.user.is_superuser:
        return redirect("article_view", name="Aktuell")

    users = (
        User.objects.filter(is_active=True)
        .order_by("stimme", "last_name", "first_name")
        .prefetch_related("user_permissions__content_type")
    )

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

        changes = data.get("changes", [])
        for change in changes:
            try:
                user = User.objects.get(pk=change["user_id"])
                perm_str = change["permission"]
                app_label, codename = perm_str.split(".", 1)
                perm = Permission.objects.get(
                    content_type__app_label=app_label,
                    codename=codename,
                )
                if change["granted"]:
                    user.user_permissions.add(perm)
                else:
                    user.user_permissions.remove(perm)
            except Exception:
                pass
        return JsonResponse({"ok": True})

    # Build initial state matrix: {str(user_id): [list of perm strings]}
    matrix = {}
    for user in users:
        user_perms = {
            f"{p.content_type.app_label}.{p.codename}"
            for p in user.user_permissions.all()
        }
        matrix[str(user.pk)] = list(user_perms)

    # Build grouped categories for the template
    cat_order: list[str] = []
    cat_map: dict[str, list] = {}
    for perm_str, label, category in PERMISSION_DEFS:
        if category not in cat_map:
            cat_map[category] = []
            cat_order.append(category)
        cat_map[category].append({"key": perm_str, "label": label})

    categories = [{"name": c, "perms": cat_map[c]} for c in cat_order]

    return render(request, "berechtigungen.html", {
        "seitentitel": "Berechtigungen",
        "users": users,
        "permission_defs": PERMISSION_DEFS,
        "categories": categories,
        "matrix_json": json.dumps(matrix),
    })
