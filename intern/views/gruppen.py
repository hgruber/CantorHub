import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, Permission
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..models import ChangeLog

__all__ = ["gruppen"]

PERMISSION_DEFS = [
    # Aktuell (Artikel)
    ("intern.delete_artikel",             "löschen",        "Artikel"),
    ("intern.manage_artikel_permissions", "Berechtigungen", "Artikel"),
    # Forum
    ("intern.add_forum",                  "anlegen",        "Forum"),
    ("intern.change_forum",               "bearbeiten",     "Forum"),
    ("intern.delete_forum",               "löschen",        "Forum"),
    # Termine
    ("intern.add_termin",                 "anlegen",        "Termine"),
    ("intern.change_termin",              "bearbeiten",     "Termine"),
    ("intern.delete_termin",              "löschen",        "Termine"),
    ("intern.change_zusage",              "Anwesenheit",    "Termine"),
    # Repertoire
    ("intern.add_lied",                   "anlegen",        "Repertoire"),
    ("intern.change_lied",                "bearbeiten",     "Repertoire"),
    ("intern.delete_lied",                "löschen",        "Repertoire"),
    # Mitglieder
    ("intern.add_user",                   "anlegen",        "Mitglieder"),
    ("intern.change_user",                "bearbeiten",     "Mitglieder"),
    ("intern.delete_user",                "löschen",        "Mitglieder"),
    # Orte
    ("intern.add_ort",                    "anlegen",        "Orte"),
    ("intern.change_ort",                 "bearbeiten",     "Orte"),
    ("intern.delete_ort",                 "löschen",        "Orte"),
    # Dateien
    ("intern.delete_folder",             "löschen",        "Dateien"),
    ("intern.manage_folder_permissions", "Berechtigungen", "Dateien"),
]

# Human-readable label for each permission string, e.g. "intern.add_artikel" → "Artikel anlegen"
_PERM_LABELS = {
    perm_str: f"{category} {label}"
    for perm_str, label, category in PERMISSION_DEFS
}


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
            group, created = Group.objects.get_or_create(name=new_name)
            initial_perm_labels = []
            for perm_str in data.get("new_group_perms", []):
                try:
                    app_label, codename = perm_str.split(".", 1)
                    perm = Permission.objects.get(
                        content_type__app_label=app_label,
                        codename=codename,
                    )
                    group.permissions.add(perm)
                    initial_perm_labels.append(_PERM_LABELS.get(perm_str, perm_str))
                except Exception:
                    pass
            if created:
                try:
                    changes = {"name": [None, group.name]}
                    if initial_perm_labels:
                        changes["berechtigungen"] = [None, ", ".join(initial_perm_labels)]
                    ChangeLog.objects.create(
                        user=request.user,
                        action=ChangeLog.ACTION_CREATE,
                        model_name="Group",
                        object_id=group.pk,
                        object_repr=group.name,
                        changes=changes,
                    )
                except Exception:
                    pass

        # Delete group (only if no users are assigned)
        del_name = (data.get("delete_group") or "").strip()
        if del_name:
            try:
                g = Group.objects.get(name=del_name)
                if not g.user_set.exists():
                    g_pk, g_name = g.pk, g.name
                    g.delete()
                    try:
                        ChangeLog.objects.create(
                            user=request.user,
                            action=ChangeLog.ACTION_DELETE,
                            model_name="Group",
                            object_id=g_pk,
                            object_repr=g_name,
                            changes={"name": [g_name, None]},
                        )
                    except Exception:
                        pass
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
                try:
                    perm_label = _PERM_LABELS.get(perm_str, perm_str)
                    ChangeLog.objects.create(
                        user=request.user,
                        action=ChangeLog.ACTION_UPDATE,
                        model_name="Group",
                        object_id=group.pk,
                        object_repr=group.name,
                        changes={"berechtigung": [None, perm_label] if change["granted"] else [perm_label, None]},
                    )
                except Exception:
                    pass
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
        "matrix": matrix,
        "group_user_counts": group_user_counts,
    })
