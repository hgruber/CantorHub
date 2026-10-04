import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from filer.models import Folder

from ..models import ChangeLog, FolderPermission, User
from ._auswahl import chip_eintraege
from ._decorators import perm_or_home
from ._pagination import ist_nachladen, nachlade_antwort, parse_offset

_PAGE_SIZE = 50

__all__ = ["aufgaben", "folder_permissions"]


@perm_or_home("intern.manage_user_permissions")
def aufgaben(request):
    groups = list(Group.objects.order_by("id"))
    # Auch Konten ohne Zugang: ein Foerdermitglied traegt das Tag „Mitglied" ohne
    # Zugang und waere hier sonst unerreichbar,
    # und damit die Mitgliedschaft im Portal nicht pflegbar. Anonymisierte Konten
    # (``mitglied_delete``) bleiben draussen; sie haben keine Gruppen mehr.
    users = (
        User.objects.exclude(username__startswith="geloescht_")
        .annotate(stimme_order=User.stimme_order_case())
        .order_by("stimme_order", "last_name", "first_name")
        .prefetch_related("groups")
    )

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

        for change in data.get("changes", []):
            try:
                user = User.objects.get(pk=change["user_id"])
                change_type = change.get("type")
                if change_type == "group":
                    group = Group.objects.get(name=change["group"])
                    if change["granted"]:
                        user.groups.add(group)
                    else:
                        user.groups.remove(group)
                    ChangeLog.objects.create(
                        user=request.user,
                        action=ChangeLog.ACTION_UPDATE,
                        model_name="User",
                        object_id=user.pk,
                        object_repr=str(user),
                        changes={"gruppe": [None, group.name] if change["granted"] else [group.name, None]},
                    )
                elif change_type == "admin" and request.user.is_superuser:
                    user._audit_user = request.user
                    user.is_superuser = change["granted"]
                    user.save(update_fields=["is_superuser"])
            except Exception:
                pass
        return JsonResponse({"ok": True})

    offset = parse_offset(request)

    page = list(users[offset : offset + _PAGE_SIZE + 1])
    has_more = len(page) > _PAGE_SIZE
    if has_more:
        page = page[:_PAGE_SIZE]

    is_admin = request.user.is_superuser
    matrix = {
        str(u.pk): {
            "groups": [g.name for g in u.groups.all()],
            **({"is_superuser": u.is_superuser} if is_admin else {}),
        }
        for u in page
    }

    if ist_nachladen(request):
        return nachlade_antwort(
            "aufgaben_rows.html",
            {"users": page, "groups": groups, "is_admin": is_admin},
            has_more, offset + _PAGE_SIZE, matrix=matrix,
        )

    return render(request, "aufgaben.html", {
        "seitentitel": "Aufgaben",
        "users": page,
        "groups": groups,
        "matrix": matrix,
        "is_admin": is_admin,
        "has_more": has_more,
        "next_offset": offset + _PAGE_SIZE,
    })


@login_required
def folder_permissions(request, pk):
    if not request.user.has_perm("intern.manage_folder_permissions"):
        raise PermissionDenied

    folder = get_object_or_404(Folder, pk=pk)

    groups = Group.objects.all().order_by("id")
    existing = {
        fp.group_id: fp
        for fp in FolderPermission.objects.filter(folder=folder)
    }

    read_restricted   = any(fp.can_read   for fp in existing.values())
    write_restricted  = any(fp.can_write  for fp in existing.values())
    delete_restricted = any(fp.can_delete for fp in existing.values())
    read_group_ids    = {gid for gid, fp in existing.items() if fp.can_read}
    write_group_ids   = {gid for gid, fp in existing.items() if fp.can_write}
    delete_group_ids  = {gid for gid, fp in existing.items() if fp.can_delete}

    if request.method == "POST":
        read_mode   = request.POST.get("read_mode")
        write_mode  = request.POST.get("write_mode")
        delete_mode = request.POST.get("delete_mode")
        read_groups   = {int(x) for x in request.POST.getlist("read_groups")}
        write_groups  = {int(x) for x in request.POST.getlist("write_groups")}
        delete_groups = {int(x) for x in request.POST.getlist("delete_groups")}

        FolderPermission.objects.filter(folder=folder).delete()

        if (
            read_mode == "restricted"
            or write_mode == "restricted"
            or delete_mode == "restricted"
        ):
            all_involved = read_groups | write_groups | delete_groups
            for gid in all_involved:
                FolderPermission.objects.create(
                    folder=folder,
                    group_id=gid,
                    can_read=(read_mode   == "restricted" and gid in read_groups),
                    can_write=(write_mode == "restricted" and gid in write_groups),
                    can_delete=(delete_mode == "restricted" and gid in delete_groups),
                )

        return redirect("folder_view", pk=folder.pk)

    from django.urls import reverse
    group_members = {
        g.id: [
            f"{u.first_name} {u.last_name}".strip() or u.username
            for u in g.user_set.filter(is_active=True).order_by("first_name", "last_name")
        ]
        for g in groups
    }
    return render(request, "folder_berechtigungen.html", {
        "seitentitel": f"Berechtigungen: {folder.name}",
        "folder": folder,
        "groups": groups,
        "read_restricted":   read_restricted,
        "write_restricted":  write_restricted,
        "delete_restricted": delete_restricted,
        "read_eintraege":    chip_eintraege(groups, read_group_ids),
        "write_eintraege":   chip_eintraege(groups, write_group_ids),
        "delete_eintraege":  chip_eintraege(groups, delete_group_ids),
        "group_members":     group_members,
        "up_url": reverse("folder_view", args=[folder.pk]),
        "id": folder.pk,
    })
