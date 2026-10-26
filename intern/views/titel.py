import json

from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, F, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig
from ._decorators import tabellenzustand
from ._pagination import ist_nachladen, nachlade_antwort, paginate_ordered, parse_offset

from filer.models import File

from intern import dateiablage, folders, liedablage, liedrollen

from ..app_settings import get_aufnahme_bezeichnung
from ..filterbau_titel import TITEL
from ..forms import LiedEditForm
from ..models import Konzert, Lied, Termin, User
from ..tables import RepertoireTabelle
from .files import _get_file_extension, _aufnahme_prefix_with_space, datei_url, visible_fields

_PAGE_SIZE = 50

__all__ = [
    "titel_list",
    "titel_playlist",
    "titel_view",
    "titel_edit",
    "titel_delete",
    "titel_add",
    "update_order",
]


def _playlist_url(request):
    """Adresse der Warteschlangen zu genau dieser Liste (Filter inbegriffen)."""
    parameter = _ohne_offset_und_sortierung(request.GET)
    pfad = reverse("titel_playlist")
    return f"{pfad}?{parameter}" if parameter else pfad


def _ohne_offset_und_sortierung(query):
    """Die Filterparameter der Liste — ohne das, was nur die Tabelle betrifft."""
    rest = query.copy()
    for name in ("offset", "sort", "edit"):
        rest.pop(name, None)
    return rest.urlencode()


def _mit_konzert(queryset, konzert_id):
    """Auf ein Konzert einschnueren.

    Das tat frueher der Filterparameter ``konzert``; seit er nicht mehr zur Kette
    gehoert (er steuert auch Ablauf und Abspieler), muss die Einschraenkung hier
    stehen -- sonst zeigte die Liste zu einem Konzert das ganze Repertoire.
    """
    if not konzert_id:
        return queryset
    return queryset.filter(konzert__termin__id=konzert_id).distinct()


def _chip_namen(bedingungen):
    """Kennung -> Name fuer die Chips: Solisten, Dirigenten, Tonarten, Tempo.

    Nur was die Kette wirklich nennt -- eine Abfrage ueber alle Mitglieder waere
    fuer jede Repertoireseite zu viel.
    """
    gebraucht = {b.feld for b in bedingungen}
    namen = {}
    if gebraucht & {"solist", "dirigent"}:
        personen = {
            str(u.pk): f"{u.last_name}, {u.first_name}".strip(", ")
            for u in User.objects.all()
        }
        namen["solist"] = personen
        namen["dirigent"] = personen
    if "tonart" in gebraucht:
        namen["tonart"] = dict(Lied.TONART_CHOICES)
    if "tempo" in gebraucht:
        from ..tables import _TEMPO_LABELS

        namen["tempo"] = _TEMPO_LABELS
    return namen


def _konzert_auswahl(konzert_id):
    """Das feste Konzertfeld: die Termine mit einem Ablauf, und der gewaehlte."""
    return {
        "aktuell": str(konzert_id) if konzert_id else "",
        "termine": list(
            Termin.objects.filter(konzert__isnull=False).distinct().order_by("-datum")
        ),
    }


@login_required
def titel_playlist(request):
    """Die Wiedergabelisten des (gefilterten) Repertoires als JSON.

    Gegenstueck zu ``folder_playlist``: der Mini-Player holt sie beim ersten Klick
    auf „Abspielen", statt sie in jede Seite einzubetten.
    """
    qs, _bedingungen = TITEL.aus_daten(_repertoire_queryset(), request.GET)
    qs = _mit_konzert(qs, request.GET.get("konzert"))
    return JsonResponse(_warteschlangen(qs))


def _warteschlangen_zaehlen(qs):
    """Wie viele Titel je Warteschlange — fuers Menue, ohne die Listen zu bauen."""
    originals = aufnahmen = alle = 0
    for rollen in liedablage.rollen_fuer(qs).values():
        original = "original" in rollen
        aufnahme = "aufnahme" in rollen
        if original:
            originals += 1
        if aufnahme:
            aufnahmen += 1
        if original or aufnahme:
            alle += 1
    return {"originals": originals, "aufnahmen": aufnahmen, "all": alle}


def _warteschlangen(qs):
    """Die drei Wiedergabelisten des Repertoires: Originale, eigene Aufnahmen, beides.

    Nur der Speicherpfad, nicht die ``File``-Zeile: fuer die URL braucht es das
    Objekt nicht, und filer legt pro Zeile ein MultiStorageFieldFile samt
    easy-thumbnails-Objekt an.
    """
    originals, aufnahmen, alle = [], [], []
    aufnahme_typ = get_aufnahme_bezeichnung()
    lieder = list(qs)
    nach_rolle = liedablage.rollen_fuer(lieder)
    for lied in lieder:
        rollen = nach_rolle[lied.pk]
        original = rollen.get("original")
        aufnahme = rollen.get("aufnahme")
        composer = lied.komponist or ""
        if original:
            originals.append({"url": datei_url(original.file.name), "title": lied.titel, "type": "Original", "composer": composer})
        if aufnahme:
            aufnahmen.append({"url": datei_url(aufnahme.file.name), "title": lied.titel, "type": aufnahme_typ, "composer": composer})
        audio = original or aufnahme
        if audio:
            alle.append({"url": datei_url(audio.file.name), "title": lied.titel, "type": "Original" if original else aufnahme_typ, "composer": composer})
    return {"originals": originals, "aufnahmen": aufnahmen, "all": alle}


def _repertoire_queryset():
    """Das Repertoire, wie Liste und Warteschlangen es brauchen.

    Die Dateien kommen nicht aus dem Queryset: ``titel_list`` verteilt die
    Rollenzeilen der Seite in einem Zugriff (``liedablage.rollen_fuer``)."""
    return (
        Lied.objects.annotate(
            zuletzt=Max("konzert__termin__datum", filter=Q(konzert__termin__datum__lte=timezone.now().date()))
        )
        .prefetch_related("solist", "dirigent")
        .order_by("titel")
    )


@login_required
@tabellenzustand
def titel_list(request):
    queryset = _repertoire_queryset()
    konzert_id = request.GET.get("konzert")
    queryset, bedingungen = TITEL.aus_daten(queryset, request.GET)
    queryset = _mit_konzert(queryset, konzert_id)
    # Kennung -> Name fuer die Chips: Solisten und Dirigenten zeigen sonst Zahlen.
    kette = TITEL.kette(bedingungen, request, _chip_namen(bedingungen))
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
        # Nur fuer render_eigenschaften -- die beiden Listen entstehen daneben aus
        # eigenen QuerySets, der Filter wirkt hier nicht.
        table = RepertoireTabelle(Lied.objects.none(), visible_fields=fields)
        RequestConfig(request, paginate=False).configure(table)

        from datetime import date

        seitentitel = f"Ablauf {Termin.objects.get(id=konzert_id)}"
        konzert_items = []
        # Ohne select_related: die Liste zeigt nur Titel und Eigenschaften,
        # die Dateien werden hier nicht angefasst.
        for i, lied in enumerate(qs):
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
                "seitentitel": seitentitel,
                "konzert_items": konzert_items,
                "pool_items": pool_items,
                "konzert_id": konzert_id,
                "konzert_back_url": f"/intern/titel/?konzert={konzert_id}",
                "add": add,
                "add_form": LiedEditForm() if request.user.has_perm("intern.add_lied") else None,
                "add_form_multipart": True,
                "add_label": "Neuer Titel",
                "feld_ordner": _feld_ordner(),
            },
        )

    # Normal repertoire table mode
    qs = queryset
    if konzert_id:
        qs = qs.annotate(position=F("konzert__position")).order_by("position")

    offset = parse_offset(request)

    probe = RepertoireTabelle(qs, visible_fields=fields)
    page, has_more = paginate_ordered(request, probe, offset, _PAGE_SIZE)
    # Die Dateien der Seite in einem Zugriff — Rollenzeile zuerst, alter FK als
    # Rückfall bis Migration 0006.
    nach_rolle = liedablage.rollen_fuer(page)
    for lied in page:
        lied.rollen = nach_rolle[lied.pk]
    table = RepertoireTabelle(page, visible_fields=fields, counter_offset=offset)
    RequestConfig(request, paginate=False).configure(table)

    if ist_nachladen(request):
        return nachlade_antwort("table_rows.html", {"table": table},
                                has_more, offset + _PAGE_SIZE)

    # Die Wiedergabelisten deckt das **gefilterte** Repertoire ab, nicht die geladene
    # Seite — eingebettet waren das 72,7 KB in jedem Seitenaufruf, fuer eine Angabe,
    # die nur braucht, wer auf „Abspielen" klickt. Die Seite traegt deshalb nur die
    # Adresse (titel_playlist) und die Anzahlen fuers Menue; die Liste selbst holt
    # intern.js beim ersten Klick. Anders als die Ordneransicht, die ihre eine
    # Warteschlange bewusst einbettet (docs/files.md).
    anzahlen = _warteschlangen_zaehlen(qs)
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
        "baukasten": TITEL,
        "bedingungen": bedingungen,
        "kette": kette,
        "filter_zusatz": "_filter_konzert.html",
        "konzert_auswahl": _konzert_auswahl(konzert_id),
        "seitentitel": seitentitel,
        "topbar_icon": '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
        "upload_folder_id": folders.musik(),
        "upload_folder_name": folders.REPERTOIRE,
        "upload_route_by_type": True,
        "showfilter": True,
        "add": add,
        "add_form": LiedEditForm() if request.user.has_perm("intern.add_lied") else None,
        "add_form_multipart": True,
        "add_label": "Neuer Titel",
        "feld_ordner": _feld_ordner(),
        "play_menu": bool(anzahlen["originals"] or anzahlen["aufnahmen"]),
        # Nicht die Listen, nur ihre Adresse — mit den Filtern der Seite, damit die
        # Warteschlange dasselbe Repertoire abdeckt wie die Liste davor.
        "playlists_url": _playlist_url(request),
        "playlist_originals_count": anzahlen["originals"],
        "playlist_aufnahmen_count": anzahlen["aufnahmen"],
        "playlist_all_count": anzahlen["all"],
        "konzert_id": konzert_id,
        "has_more": has_more,
        "next_offset": offset + _PAGE_SIZE,
    }
    if konzert_id and request.user.has_perm("intern.change_lied"):
        context["konzert_order_url"] = f"/intern/titel/?konzert={konzert_id}&edit"
    return render(request, "table.html", context)


def _feld_ordner():
    """Die Zielordner der Datei-Felder eines Titels — die Feld-Dropzone lädt
    gleich dorthin, nicht erst beim Speichern (siehe `_titeldatei_ablegen`)."""
    return {
        "original": folders.repertoire(),
        "aufnahme": folders.repertoire(),
        "pdf": folders.pdf(),
        "noten": folders.notensatz(),
    }


def _titeldatei_ablegen(f, feld, ordner_fn, titel):
    """Eine hochgeladene Titel-Datei in ihren Ordner, benannt nach dem Titel.

    Liegt dort schon eine Datei dieses Namens (die bisherige des Titels), wird
    die neue ihre vordere Fassung; zurück kommt die Zeile, auf die der Titel
    zeigen soll."""
    ext = _get_file_extension(f.original_filename or f.name or "")
    praefix = _aufnahme_prefix_with_space() if feld == "aufnahme" else ""
    return dateiablage.systemablage(f, ordner_fn() or f.folder_id, f"{praefix}{titel}{ext}")


_ROLLEN_CSS = {"notenblatt": " file-icon-btn--pdf", "notensatz": " file-icon-btn--notes"}


def _medien(lied):
    """Die Dateien des Liedes in Anzeigereihenfolge — eine Schleife im Template
    statt eines Blocks je Rolle."""
    rollen = liedablage.rollen_von(lied)
    aufnahme_typ = get_aufnahme_bezeichnung()
    medien = []
    for definition in liedrollen.ROLLEN:
        datei = rollen.get(definition.key)
        if not datei:
            continue
        if definition.key == "original":
            medien.append({
                "rolle": definition.key,
                "label": definition.label,
                "url": datei.url,
                "audio": True,
                "song_id": str(lied.id),
                "typ": definition.label,
                "logo": False,
            })
        elif definition.key == "aufnahme":
            medien.append({
                "rolle": definition.key,
                "label": aufnahme_typ,
                "url": datei.url,
                "audio": True,
                "song_id": f"r{lied.id}",
                "typ": aufnahme_typ,
                "logo": True,
            })
        else:
            medien.append({
                "rolle": definition.key,
                "label": definition.label,
                "url": datei.url,
                "audio": False,
                "css": _ROLLEN_CSS.get(definition.key, ""),
            })
    return medien


@login_required
def titel_view(request, titel):
    lied = get_object_or_404(Lied.objects.prefetch_related("solist", "dirigent"), id=titel)
    context = {
        "seitentitel": lied.titel,
        "lied": lied,
        "medien": _medien(lied),
        "up": "titel_list",
        "edit": "titel_edit" if request.user.has_perm("intern.change_lied") else None,
        "history": "titel_aenderungen" if request.user.has_perm("intern.change_lied") else None,
        "id": titel,
        "upload_folder_id": folders.musik(),
        "upload_folder_name": folders.REPERTOIRE,
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
            abgelegt = {}
            for field_name, folder_fn in _FILER_EDIT_MAP.items():
                new_id = request.POST.get(field_name)
                old_id = str(getattr(lied, field_name + "_id") or "") if hasattr(lied, field_name + "_id") else ""
                if new_id and new_id != old_id:
                    try:
                        f = File.objects.get(pk=int(new_id))
                        abgelegt[field_name] = _titeldatei_ablegen(f, field_name, folder_fn, lied.titel)
                    except (File.DoesNotExist, ValueError):
                        pass
            instance = form.save(commit=False)
            # Hat die Ablage die neue Datei mit der bisherigen verschmolzen,
            # gilt deren Zeile — nicht die aus dem Formular.
            for field_name, zeile in abgelegt.items():
                setattr(instance, field_name, zeile)
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
        "feld_ordner": _feld_ordner(),
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
                        setattr(lied, model_field,
                                _titeldatei_ablegen(f, model_field, folder_fn, lied.titel))
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
        "feld_ordner": _feld_ordner(),
    }
    return render(request, "titel_edit.html", context)