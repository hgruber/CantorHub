from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from ..app_settings import get_config_int, get_map_center
from ..models import ADDRESS_TRIGGER_FIELDS, Ort, Standort, User

__all__ = [
    "karte_view",
    "karte_standorte_live",
    "karte_ort_create",
    "karte_ort_detail",
    "karte_standort",
]


def _standorte_data(current_user):
    return [
        {"person_id": s.person_id,
         "name": f"{s.person.first_name} {s.person.last_name}".strip() or s.person.username,
         "breite": s.breite, "laenge": s.laenge,
         "aktualisiert": s.aktualisiert.strftime("%d.%m.%Y %H:%M"),
         "ich": s.person_id == current_user.id}
        for s in Standort.objects.select_related("person").all()
    ]


@login_required
def karte_view(request):
    orte = [
        {"id": o.id, "name": o.name, "breite": o.breite, "laenge": o.laenge,
         "adresse": ", ".join(filter(None, [o.strasse, f"{o.plz or ''} {o.ort or ''}".strip()]))}
        for o in Ort.objects.filter(breite__isnull=False, laenge__isnull=False)
    ]
    viewer = request.user
    members = []
    for u in User.objects.filter(is_active=True, breite__isnull=False, laenge__isnull=False):
        hidden = set(u.private_fields or [])
        if hidden & ADDRESS_TRIGGER_FIELDS and not (
            viewer.id == u.id or viewer.has_perm("intern.change_user")
        ):
            continue
        members.append({
            "id": u.id,
            "name": f"{u.first_name} {u.last_name}".strip() or u.username,
            "breite": u.breite,
            "laenge": u.laenge,
        })
    standorte = _standorte_data(request.user)
    map_center = get_map_center()
    return render(request, "karte.html", {
        "seitentitel": "Karte",
        "orte_json": orte,
        "members_json": members,
        "standorte_json": standorte,
        "show_search": True,
        "search_query": (request.GET.get("q") or "").strip(),
        "map_center_lat": str(map_center[0]),
        "map_center_lng": str(map_center[1]),
        "map_default_zoom": get_config_int("MAP_DEFAULT_ZOOM", 12),
    })


@login_required
def karte_standorte_live(request):
    return JsonResponse({"standorte": _standorte_data(request.user)})


@login_required
@require_POST
def karte_ort_create(request):
    if not request.user.has_perm("intern.add_ort"):
        return JsonResponse({"error": "Keine Berechtigung"}, status=403)
    name = request.POST.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "Name fehlt"}, status=400)
    try:
        breite = float(request.POST.get("breite", "")) if request.POST.get("breite") else None
        laenge = float(request.POST.get("laenge", "")) if request.POST.get("laenge") else None
    except ValueError:
        return JsonResponse({"error": "Ungültige Koordinaten"}, status=400)
    ort = Ort.objects.create(
        name=name,
        strasse=request.POST.get("strasse", "").strip() or None,
        plz=request.POST.get("plz", "").strip() or None,
        ort=request.POST.get("ort_name", "").strip() or None,
        breite=breite,
        laenge=laenge,
    )
    return JsonResponse({"id": ort.id, "name": ort.name, "breite": ort.breite, "laenge": ort.laenge})


@login_required
def karte_ort_detail(request, pk):
    ort = get_object_or_404(Ort, pk=pk)
    if request.method == "GET":
        return JsonResponse({
            "id": ort.id, "name": ort.name,
            "strasse": ort.strasse or "", "plz": ort.plz or "", "ort_name": ort.ort or "",
            "breite": ort.breite, "laenge": ort.laenge,
        })
    if request.POST.get("delete"):
        if not request.user.has_perm("intern.delete_ort"):
            return JsonResponse({"error": "Keine Berechtigung"}, status=403)
        ort._audit_user = request.user
        ort.delete()
        return JsonResponse({"deleted": True})
    if not request.user.has_perm("intern.change_ort"):
        return JsonResponse({"error": "Keine Berechtigung"}, status=403)
    name = request.POST.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "Name fehlt"}, status=400)
    try:
        breite = float(request.POST.get("breite", "")) if request.POST.get("breite") else None
        laenge = float(request.POST.get("laenge", "")) if request.POST.get("laenge") else None
    except ValueError:
        return JsonResponse({"error": "Ungültige Koordinaten"}, status=400)
    ort.name = name
    ort.strasse = request.POST.get("strasse", "").strip() or None
    ort.plz = request.POST.get("plz", "").strip() or None
    ort.ort = request.POST.get("ort_name", "").strip() or None
    ort.breite = breite
    ort.laenge = laenge
    ort.save()
    adresse = ", ".join(filter(None, [ort.strasse, f"{ort.plz or ''} {ort.ort or ''}".strip()]))
    return JsonResponse({"id": ort.id, "name": ort.name, "breite": ort.breite, "laenge": ort.laenge, "adresse": adresse})


@login_required
@require_POST
def karte_standort(request):
    try:
        breite = float(request.POST.get("breite", ""))
        laenge = float(request.POST.get("laenge", ""))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Ungültige Koordinaten"}, status=400)
    standort, _ = Standort.objects.update_or_create(
        person=request.user,
        defaults={"breite": breite, "laenge": laenge},
    )
    return JsonResponse({
        "breite": standort.breite,
        "laenge": standort.laenge,
        "aktualisiert": standort.aktualisiert.strftime("%d.%m.%Y %H:%M"),
    })