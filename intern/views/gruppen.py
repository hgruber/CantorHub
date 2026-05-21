import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, Permission
from django.http import JsonResponse
from django.shortcuts import redirect, render

__all__ = ["gruppen"]

PERMISSION_DEFS = [
    ("intern.add_artikel",    "anlegen",      "Artikel"),
    ("intern.change_artikel", "bearbeiten",   "Artikel"),
    ("intern.delete_artikel", "löschen",      "Artikel"),
    ("intern.add_forum",      "anlegen",      "Forum"),
    ("intern.change_forum",   "bearbeiten",   "Forum"),
    ("intern.delete_forum",   "löschen",      "Forum"),
    ("filer.add_folder",      "anlegen",      "Dateien"),
    ("filer.change_folder",   "bearbeiten",   "Dateien"),
    ("filer.delete_folder",   "löschen",      "Dateien"),
    ("intern.add_ort",        "anlegen",      "Orte"),
    ("intern.change_ort",     "bearbeiten",   "Orte"),
    ("intern.delete_ort",     "löschen",      "Orte"),
    ("intern.add_termin",     "anlegen",      "Termine"),
    ("intern.change_termin",  "bearbeiten",   "Termine"),
    ("intern.delete_termin",  "löschen",      "Termine"),
    ("intern.change_zusage",  "Anwesenheit",  "Termine"),
    ("intern.add_lied",       "anlegen",      "Repertoire"),
    ("intern.change_lied",    "bearbeiten",   "Repertoire"),
    ("intern.delete_lied",    "löschen",      "Repertoire"),
    ("intern.add_user",       "anlegen",      "Mitglieder"),
    ("intern.change_user",    "bearbeiten",   "Mitglieder"),
    ("intern.delete_user",    "löschen",      "Mitglieder"),
]


@login_required
def gruppen(request):
    if not request.user.is_superuser:
        return redirect("article_view", name="Aktuell")

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

        # Create new group
        new_name = (data.get("new_group") or "").strip()
        if new_name:
            group, _ = Group.objects.get_or_create(name=new_name)
            for perm_str in data.get("new_group_perms", []):
                try:
                    app_label, codename = perm_str.split(".", 1)
                    perm = Permission.objects.get(
                        content_type__app_label=app_label,
                        codename=codename,
                    )
                    group.permissions.add(perm)
                except Exception:
                    pass

        # Delete group (only if no users are assigned)
        del_name = (data.get("delete_group") or "").strip()
        if del_name:
            try:
                g = Group.objects.get(name=del_name)
                if not g.user_set.exists():
                    g.delete()
            except Group.DoesNotExist:
                pass

        # Toggle group permissions
        for change in data.get("changes", []):
            try:
                group = Group.objects.get(name=change["group"])
                perm_str = change["permission"]
                app_label, codename = perm_str.split(".", 1)
                perm = Permission.objects.get(
                    content_type__app_label=app_label,
                    codename=codename,
                )
                if change["granted"]:
                    group.permissions.add(perm)
                else:
                    group.permissions.remove(perm)
            except Exception:
                pass

        return JsonResponse({"ok": True})

    all_groups = list(
        Group.objects.order_by("name").prefetch_related("permissions__content_type")
    )

    # Build permission matrix: {group_name: [perm_strings]}
    matrix = {
        g.name: [
            f"{p.content_type.app_label}.{p.codename}"
            for p in g.permissions.all()
        ]
        for g in all_groups
    }

    # Build category structure for template header (same as berechtigungen)
    cat_order: list[str] = []
    cat_map: dict[str, list] = {}
    for perm_str, label, category in PERMISSION_DEFS:
        if category not in cat_map:
            cat_map[category] = []
            cat_order.append(category)
        cat_map[category].append({"key": perm_str, "label": label})
    categories = [{"name": c, "perms": cat_map[c]} for c in cat_order]

    # User count per group to guard the delete button
    group_user_counts = {g.name: g.user_set.count() for g in all_groups}

    return render(request, "gruppen.html", {
        "seitentitel": "Gruppen",
        "groups": all_groups,
        "categories": categories,
        "permission_defs": PERMISSION_DEFS,
        "matrix_json": json.dumps(matrix),
        "group_user_counts_json": json.dumps(group_user_counts),
    })
