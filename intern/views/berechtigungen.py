import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db.models import Case, IntegerField, Value, When
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..models import User

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
                elif change_type == "admin":
                    user.is_superuser = change["granted"]
                    user.save(update_fields=["is_superuser"])
            except Exception:
                pass
        return JsonResponse({"ok": True})

    # Build initial state matrix: {str(user_id): {"groups": [...], "is_superuser": bool}}
    matrix = {
        str(u.pk): {
            "groups": [g.name for g in u.groups.all()],
            "is_superuser": u.is_superuser,
        }
        for u in users
    }

    return render(request, "berechtigungen.html", {
        "seitentitel": "Berechtigungen",
        "users": users,
        "groups": groups,
        "matrix_json": json.dumps(matrix),
    })
