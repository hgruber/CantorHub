import json

from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, F, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig

from filer.models import File

from intern import folders

from ..forms import LiedEditForm
from ..models import Konzert, Lied, Termin
from ..tables import RepertoireFilter, RepertoireTabelle
from .files import visible_fields, _get_file_extension

_PAGE_SIZE = 50

__all__ = [
    "titel_list",
    "titel_view",
    "titel_edit",
    "titel_delete",
    "titel_add",
    "update_order",
]


@login_required
def titel_list(request):
    queryset = Lied.objects.annotate(
        zuletzt=Max("konzert__termin__datum", filter=Q(konzert__termin__datum__lte=timezone.now().date()))
    ).order_by("titel")
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
            Lied.objects.filter(konzert__termin__id=konzert_id)
            .annotate(position=F("konzert__position"))
            .order_by("position")
        )
        fields = ["titel", "eigenschaften", "position"]
        table = RepertoireTabelle(
            repertoire_filter.qs, visible_fields=fields
        )
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
        pool_items = []
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
                "chips_skip": ["konzert"],
            },
        )

    # Normal repertoire table mode
    qs = repertoire_filter.qs
    if konzert_id:
        qs = qs.annotate(position=F("konzert__position")).order_by("position")

    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0

    page = list(qs[offset : offset + _PAGE_SIZE + 1])
    has_more = len(page) > _PAGE_SIZE
    if has_more:
        page = page[:_PAGE_SIZE]

    table = RepertoireTabelle(page, visible_fields=fields, counter_offset=offset)
    RequestConfig(request, paginate=False).configure(table)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        html = render_to_string("table_rows.html", {"table": table})
        return JsonResponse({
            "html": html,
            "has_more": has_more,
            "next_offset": offset + _PAGE_SIZE,
        })

    # Playlists must include every (filtered) song so the player works for any row,
    # not just the first page — build them from the full qs on initial render only.
    playlist_originals, playlist_aufnahmen, playlist_all = [], [], []
    for lied in qs.select_related("original", "aufnahme"):
        composer = lied.komponist or ""
        if lied.original:
            playlist_originals.append({"url": lied.original.url, "title": lied.titel, "type": "Original", "composer": composer})
        if lied.aufnahme:
            playlist_aufnahmen.append({"url": lied.aufnahme.url, "title": lied.titel, "type": "JG Aufnahme", "composer": composer})
        audio = lied.original or lied.aufnahme
        if audio:
            playlist_all.append({"url": audio.url, "title": lied.titel, "type": "Original" if lied.original else "JG Aufnahme", "composer": composer})
    playlists = {"originals": playlist_originals, "aufnahmen": playlist_aufnahmen, "all": playlist_all}
    column_choices = [
        {
            "name": name,
            "label": table.columns[name].header,
            "checked": name in fields,
        }
        for name in table.base_columns
        if name != "position"
    ]

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
        "topbar_icon": '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
        "upload_folder_id": folders.musik(),
        "upload_route_by_type": True,
        "showfilter": True,
        "add": add,
        "add_form": LiedEditForm() if request.user.has_perm("intern.add_lied") else None,
        "add_form_multipart": True,
        "add_label": "Neuer Titel",
        "play_menu": bool(playlist_originals or playlist_aufnahmen),
        "playlists": playlists,
        "playlist_originals_count": len(playlist_originals),
        "playlist_aufnahmen_count": len(playlist_aufnahmen),
        "playlist_all_count": len(playlist_all),
        "konzert_id": konzert_id,
        "chips_skip": ["konzert"],
        "has_more": has_more,
        "next_offset": offset + _PAGE_SIZE,
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
        "history": "titel_aenderungen" if request.user.has_perm("intern.change_lied") else None,
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
            instance = form.save(commit=False)
            instance._audit_user = request.user
            instance.save()
            form.save_m2m()
            return redirect("titel_view", titel=titel)
    else:
        form = LiedEditForm(instance=lied)

    konzerte_count = lied.konzert_set.count()
    solist_count   = lied.solist.count()
    dirigent_count = lied.dirigent.count()
    blocking = []
    if konzerte_count:
        blocking.append(f"{konzerte_count} Konzert{'e' if konzerte_count != 1 else ''}")
    if solist_count:
        blocking.append(f"{solist_count} Solist{'en' if solist_count != 1 else ''}")
    if dirigent_count:
        blocking.append(f"{dirigent_count} Dirigent{'en' if dirigent_count != 1 else ''}")

    context = {
        "form": form,
        "lied": lied,
        "seitentitel": f"bearbeiten: {lied.titel}",
        "view": "titel_view",
        "id": titel,
        "konzerte_count": konzerte_count,
        "can_delete": not blocking,
        "delete_tooltip": ("Kann nicht gelöscht werden: " + ", ".join(blocking)) if blocking else "",
    }
    return render(request, "titel_edit.html", context)


@permission_required("intern.delete_lied", raise_exception=True)
@require_POST
def titel_delete(request, titel):
    lied = get_object_or_404(Lied, id=titel)
    if lied.konzert_set.exists() or lied.solist.exists() or lied.dirigent.exists():
        return redirect("titel_edit", titel=titel)
    lied._audit_user = request.user
    lied.delete()
    return redirect("titel_list")


@permission_required("intern.change_lied", raise_exception=True)
@require_POST
def update_order(request):
    from ..models import ChangeLog
    try:
        data = json.loads(request.body)
        konzert_id = data.get("konzert_id")
        order = data.get("order", [])

        old_titles = list(
            Konzert.objects.filter(termin_id=konzert_id)
            .select_related("lied").order_by("position")
            .values_list("lied__titel", flat=True)
        )

        Konzert.objects.filter(termin__id=konzert_id).delete()
        k = [
            Konzert(position=position, lied_id=lied_id, termin_id=konzert_id)
            for position, lied_id in enumerate(order)
        ]
        Konzert.objects.bulk_create(k)

        new_titles = list(
            Konzert.objects.filter(termin_id=konzert_id)
            .select_related("lied").order_by("position")
            .values_list("lied__titel", flat=True)
        )

        if old_titles != new_titles:
            termin = Termin.objects.filter(pk=konzert_id).first()
            ChangeLog.objects.create(
                user=request.user,
                action=ChangeLog.ACTION_UPDATE,
                model_name="Konzert",
                object_id=konzert_id,
                object_repr=str(termin) if termin else f"Termin #{konzert_id}",
                changes={"setlist": [
                    ", ".join(old_titles) or "–",
                    ", ".join(new_titles) or "–",
                ]},
            )

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
            lied._audit_user = request.user
            lied.save()
            form.save_m2m()
            return redirect("titel_view", titel=lied.id)
    else:
        form = LiedEditForm()
    context = {
        "form": form,
        "seitentitel": "Neuer Titel",
    }
    return render(request, "titel_edit.html", context)