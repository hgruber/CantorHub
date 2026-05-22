import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db.models import Case, IntegerField, Value, When
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string

from ..models import ChangeLog, User

_PAGE_SIZE = 50

STIMME_ORDER = Case(
    When(stimme="S", then=Value(0)),
    When(stimme="A", then=Value(1)),
    When(stimme="T", then=Value(2)),
    When(stimme="B", then=Value(3)),
    When(stimme="C", then=Value(4)),
    When(stimme="M", then=Value(5)),
    default=Value(6),
    output_field=IntegerField(),
)

__all__ = ["berechtigungen"]


@login_required
def berechtigungen(request):
    if not request.user.is_superuser:
        return redirect("article_view", name="Aktuell")

    groups = list(Group.objects.order_by("name"))
    users = (
        User.objects.filter(is_active=True)
        .annotate(stimme_order=STIMME_ORDER)
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
                elif change_type == "admin":
                    user._audit_user = request.user
                    user.is_superuser = change["granted"]
                    user.save(update_fields=["is_superuser"])
            except Exception:
                pass
        return JsonResponse({"ok": True})

    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0

    page = list(users[offset : offset + _PAGE_SIZE + 1])
    has_more = len(page) > _PAGE_SIZE
    if has_more:
        page = page[:_PAGE_SIZE]

    matrix = {
        str(u.pk): {
            "groups": [g.name for g in u.groups.all()],
            "is_superuser": u.is_superuser,
        }
        for u in page
    }

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        html = render_to_string(
            "berechtigungen_rows.html",
            {"users": page, "groups": groups},
        )
        return JsonResponse({
            "html": html,
            "matrix": matrix,
            "has_more": has_more,
            "next_offset": offset + _PAGE_SIZE,
        })

    return render(request, "berechtigungen.html", {
        "seitentitel": "Berechtigungen",
        "users": page,
        "groups": groups,
        "matrix_json": json.dumps(matrix),
        "has_more": has_more,
        "next_offset": offset + _PAGE_SIZE,
    })
