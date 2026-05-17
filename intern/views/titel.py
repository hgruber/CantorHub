import json

from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig

from filer.models import File

from intern import folders

from ..forms import LiedEditForm
from ..models import Konzert, Lied, Termin
from ..tables import RepertoireFilter, RepertoireTabelle
from .files import visible_fields, _get_file_extension

__all__ = [
    "titel_list",
    "titel_view",
    "titel_edit",
    "titel_add",
    "update_order",
]


@login_required
def titel_list(request):
    queryset = Lied.objects.order_by("titel")
    konzert_id = request.GET.get("konzert")
    repertoire_filter = RepertoireFilter(request.GET, queryset=queryset)
    fields = visible_fields(request, "RepertoireTabelle")
    # Legacy single-property columns now live in one Eigenschaften column
    _LEGACY_EIG = {"aktiv", "tempo", "beats", "hymne", "acapella", "weihnacht"}
    if _LEGACY_EIG.intersection(fields):
        fields = [f for f in fields if f not in _LEGACY_EIG]
        if "eigenschaften" not in fields:
            fields.append("eigenschaften")

    # Konzert reorder mode: split-screen layout
    if konzert_id and "edit" in request.GET:
        qs = (
            repertoire_filter.qs.annotate(position=F("konzert__position"))
            .distinct()
            .order_by("position")
        )
        fields = ["titel", "eigenschaften", "position"]
        table = RepertoireTabelle(qs, visible_fields=fields)
        RequestConfig(request, paginate=False).configure(table)

        from datetime import date

        seitentitel = f"Ablauf {Termin.objects.get(id=konzert_id)}"
        konzert_items = []
        for i, lied in enumerate(qs.select_related("original", "aufnahme")):
            konzert_items.append({
                "id": lied.id,
                "titel": lied.titel,
                "position": i + 1,
                "eigenschaften": table.render_eigenschaften(lied),
            })
        remaining_qs = (
            Lied.objects.exclude(konzert__termin__id=konzert_id)
            .annotate(
                cnt=Count(
                    1,
                    filter=Q(konzert__termin__datum__gt=date(2015, 12, 23)),
                ),
            )
            .order_by("-cnt", "titel")
        )
        pool_items = []
        for lied in remaining_qs:
            pool_items.append({
                "id": lied.id,
                "titel": lied.titel,
                "eigenschaften": table.render_eigenschaften(lied),
            })

        add = "titel_add" if request.user.has_perm("intern.add_lied") else None
        return render(
            request,
            "titel_split.html",
            {
                "filter": repertoire_filter,
                "seitentitel": seitentitel,
                "konzert_items": konzert_items,
                "pool_items": pool_items,
                "konzert_id": konzert_id,
                "konzert_back_url": f"/intern/titel/?konzert={konzert_id}",
                "add": add,
                "add_form": LiedEditForm() if request.user.has_perm("intern.add_lied") else None,
                "add_form_multipart": True,
                "add_label": "Neuer Titel",
            },
        )

    # Normal repertoire table mode
    qs = repertoire_filter.qs
    if konzert_id:
        qs = qs.annotate(position=F("konzert__position")).order_by("position")
    table = RepertoireTabelle(qs, visible_fields=fields)
    playlist = []
    for lied in qs.select_related("original", "aufnahme"):
        audio = lied.original or lied.aufnahme
        if not audio:
            continue
        playlist.append({
            "url": audio.url,
            "title": lied.titel,
            "type": "Original" if lied.original else "JG Aufnahme",
        })
    column_choices = [
        {
            "name": name,
            "label": table.columns[name].header,
            "checked": name in fields,
        }
        for name in table.base_columns
        if name != "position"
    ]
    RequestConfig(request, paginate=False).configure(table)

    add = "titel_add" if request.user.has_perm("intern.add_lied") else None
    seitentitel = "Repertoire"
    if konzert_id:
        try:
            seitentitel = str(Termin.objects.get(id=konzert_id))
        except Termin.DoesNotExist:
            pass
    context = {
        "table": table,
        "column_choices": column_choices,
        "visible_fields": fields,
        "filter": repertoire_filter,
        "seitentitel": seitentitel,
        "upload_folder_id": folders.musik(),
        "upload_route_by_type": True,
        "showfilter": True,
        "add": add,
        "add_form": LiedEditForm() if request.user.has_perm("intern.add_lied") else None,
        "add_form_multipart": True,
        "add_label": "Neuer Titel",
        "playall": bool(playlist),
        "playlist_json": json.dumps(playlist, ensure_ascii=False),
        "konzert_id": konzert_id,
    }
    if konzert_id and request.user.has_perm("intern.change_lied"):
        context["konzert_order_url"] = f"/intern/titel/?konzert={konzert_id}&edit"
    return render(request, "table.html", context)


@login_required
def titel_view(request, titel):
    lied = get_object_or_404(Lied.objects.prefetch_related("solist", "dirigent"), id=titel)
    context = {
        "seitentitel": lied.titel,
        "lied": lied,
        "up": "titel_list",
        "edit": "titel_edit",
        "id": titel,
        "upload_folder_id": folders.musik(),
        "upload_route_by_type": True,
        "upload_lied_id": titel,
    }
    return render(request, "titel.html", context)


@permission_required("intern.change_lied", raise_exception=True)
def titel_edit(request, titel):
    lied = get_object_or_404(Lied, id=titel)

    if request.method == "POST":
        form = LiedEditForm(request.POST, request.FILES, instance=lied)
        if form.is_valid():
            # Move dropzone-uploaded files to their correct folders
            _FILER_EDIT_MAP = {
                "original": folders.repertoire,
                "aufnahme": folders.repertoire,
                "pdf": folders.pdf,
                "noten": folders.notensatz,
            }
            for field_name, folder_fn in _FILER_EDIT_MAP.items():
                new_id = request.POST.get(field_name)
                old_id = str(getattr(lied, field_name + "_id") or "") if hasattr(lied, field_name + "_id") else ""
                if new_id and new_id != old_id:
                    try:
                        f = File.objects.get(pk=int(new_id))
                        folder_id = folder_fn()
                        if folder_id:
                            f.folder_id = folder_id
                        ext = _get_file_extension(f.original_filename or f.name or "")
                        if field_name == "aufnahme":
                            new_name = f"JG - {lied.titel}{ext}"
                        else:
                            new_name = f"{lied.titel}{ext}"
                        f.original_filename = new_name
                        f.name = new_name
                        f.save()
                    except (File.DoesNotExist, ValueError):
                        pass
            form.save()
            return redirect("titel_view", titel=titel)
    else:
        form = LiedEditForm(instance=lied)

    context = {
        "form": form,
        "seitentitel": f"bearbeiten: {lied.titel}",
        "view": "titel_view",
        "id": titel,
    }
    return render(request, "titel_edit.html", context)


@permission_required("intern.change_lied", raise_exception=True)
@require_POST
def update_order(request):
    try:
        data = json.loads(request.body)
        konzert_id = data.get("konzert_id")
        order = data.get("order", [])
        Konzert.objects.filter(termin__id=konzert_id).delete()
        k = [
            Konzert(position=position, lied_id=lied_id, termin_id=konzert_id)
            for position, lied_id in enumerate(order)
        ]
        Konzert.objects.bulk_create(k)
        return JsonResponse({"status": "success"})

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@permission_required("intern.add_lied", raise_exception=True)
def titel_add(request):
    if request.method == "POST":
        form = LiedEditForm(request.POST, request.FILES)
        if form.is_valid():
            lied = form.save(commit=False)
            # Handle dropzone-uploaded files: filer IDs come as <field>_filer_id
            _FILER_FIELD_MAP = {
                "original_filer_id": ("original", folders.repertoire),
                "aufnahme_filer_id": ("aufnahme", folders.repertoire),
                "pdf_filer_id": ("pdf", folders.pdf),
                "noten_filer_id": ("noten", folders.notensatz),
            }
            for post_key, (model_field, folder_fn) in _FILER_FIELD_MAP.items():
                filer_id = request.POST.get(post_key)
                if filer_id:
                    try:
                        f = File.objects.get(pk=int(filer_id))
                        # Move file to its final folder
                        folder_id = folder_fn()
                        if folder_id:
                            f.folder_id = folder_id
                        # Rename file to match the song title
                        ext = _get_file_extension(f.original_filename or f.name or "")
                        new_name = f"JG - {lied.titel}{ext}" if model_field == "aufnahme" else f"{lied.titel}{ext}"
                        f.name = new_name
                        f.original_filename = new_name
                        f.save()
                        setattr(lied, model_field, f)
                    except (File.DoesNotExist, ValueError):
                        pass
            lied.save()
            return redirect("titel_view", titel=lied.id)
    else:
        form = LiedEditForm()
    context = {
        "form": form,
        "seitentitel": "Neuer Titel",
    }
    return render(request, "titel_edit.html", context)