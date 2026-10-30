import json
import mimetypes

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig
from easy_thumbnails.files import get_thumbnailer
from ._decorators import tabellenzustand
from ._pagination import ist_nachladen, nachlade_antwort, paginate_ordered, parse_offset

from filer.models import File, Folder

from intern import dateiablage, folders, liedablage, liedrollen
from intern.avatar_access import darf_avatar_aendern
from intern.folder_access import visible_folder_ids

from ..app_settings import get_aufnahme_bezeichnung
from ..filterbau_titel import TITEL
from ..forms import LiedEditForm
from ..medientypen import medientyp
from ..models import Konzert, Lied, LiedDatei, Termin, User
from ..tables import RepertoireTabelle, datei_symbol
from .files import datei_url, visible_fields

_PAGE_SIZE = 50

__all__ = [
    "titel_list",
    "titel_playlist",
    "titel_view",
    "titel_edit",
    "titel_rolle",
    "titel_datei",
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
        "showfilter": True,
        "add": add,
        "add_form": LiedEditForm() if request.user.has_perm("intern.add_lied") else None,
        "add_form_multipart": True,
        "add_label": "Neuer Titel",
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
    if request.user.has_perm("intern.change_lied"):
        # Jede Zeile nimmt Dateien für ihr Lied an (intern.js) — nur mit dem Recht,
        # das upload() für eine lied_id verlangt.
        context["upload_lied_zeilen"] = True
        if konzert_id:
            context["konzert_order_url"] = f"/intern/titel/?konzert={konzert_id}&edit"
    return render(request, "table.html", context)


_ROLLEN_CSS = {"notenblatt": " file-icon-btn--pdf", "notensatz": " file-icon-btn--notes"}

# Wovon easy_thumbnails ein Bild rechnet — dieselbe Menge wie im Dateibrowser
# (`folders._attach_thumbnails`).
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _mime(datei):
    """filer setzt `mime_type` nicht zuverlässig; die Endung ist der Rückfall."""
    mime = datei.mime_type or ""
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(datei.original_filename or datei.name or "")[0] or ""
    return mime


def _vorschau_von(datei):
    """Ein kleines Vorschaubild, sonst das Symbol des Dateityps."""
    name = datei.original_filename or datei.name or ""
    mime = _mime(datei)
    if mime.startswith("image/") or mime.endswith("pdf") or mime == _DOCX_MIME:
        try:
            return get_thumbnailer(datei.file).get_thumbnail(
                {"size": (64, 64), "crop": True, "quality": 85}
            ).url
        except Exception:
            pass
    return datei_symbol(name, mime)


def _medien(lied, ordner_sichtbar=True):
    """Alle Dateien des Liedes: die mit Rolle zuerst, dann die rollenlosen.

    Die Rollenzeile gibt die Reihenfolge vor; was im Lied-Ordner liegt, ohne
    eine Rolle zu tragen, folgt dahinter mit seinem Dateinamen — nur, wenn der
    Betrachter den Ordner sehen darf (`ordner_sichtbar`). Jede Datei hat eine
    Vorschau; was der Player abspielen kann, bekommt einen Play-Knopf."""
    rollen = liedablage.rollen_von(lied)
    aufnahme_typ = get_aufnahme_bezeichnung()
    medien = []
    mit_rolle = set()

    def eintrag(datei, label, **extra):
        name = datei.original_filename or datei.name or ""
        return {
            "rolle": "",
            "label": label,
            "url": datei.url,
            "vorschau": _vorschau_von(datei),
            "audio": medientyp(_mime(datei), name) == "audio",
            "song_id": f"d{datei.pk}",
            "typ": label,
            "logo": False,
            "css": "",
            **extra,
        }

    for definition in liedrollen.ROLLEN:
        datei = rollen.get(definition.key)
        if not datei:
            continue
        mit_rolle.add(datei.pk)
        if definition.key == "original":
            medien.append(eintrag(datei, definition.label, rolle="original", song_id=str(lied.id)))
        elif definition.key == "aufnahme":
            medien.append(eintrag(
                datei, aufnahme_typ, rolle="aufnahme", song_id=f"r{lied.id}", logo=True,
            ))
        else:
            medien.append(eintrag(
                datei, definition.label, rolle=definition.key,
                css=_ROLLEN_CSS.get(definition.key, ""),
            ))
    for datei in liedablage.dateien_im_ordner(lied) if ordner_sichtbar else ():
        if datei.pk in mit_rolle:
            continue
        medien.append(eintrag(datei, datei.original_filename or datei.name, ohne_rolle=True))
    return medien


def _medien_dateien(lied):
    """Die Dateien der Medien-Karte auf der Bearbeiten-Seite: je Datei eine
    Zeile mit ihrem Dateinamen und allen ihren Rollen.

    Eine Datei trägt höchstens eine Rolle (``liedablage.rolle_setzen``); hat sie
    aus Altbestand mehrere, bleibt sie trotzdem eine Zeile. Dateien mit Rolle
    stehen vorn, in Rollenreihenfolge, dann der Rest des Lied-Ordners."""
    zeilen = {}

    def zeile(datei):
        return zeilen.setdefault(datei.pk, {
            "datei_id": datei.pk,
            "dateiname": datei.original_filename or datei.name,
            "url": datei.url,
            "rollen": [],
            # Altbestand oder im Dateibrowser verschoben: die Rolle lässt sich
            # lösen, umbenannt und gelöscht wird nur im eigenen Ordner.
            "im_ordner": datei.folder_id == lied.ordner_id,
        })

    rollen = liedablage.rollen_von(lied)
    for definition in liedrollen.ROLLEN:
        datei = rollen.get(definition.key)
        if datei:
            zeile(datei)["rollen"].append({"key": definition.key, "label": definition.label})
    for datei in liedablage.dateien_im_ordner(lied):
        zeile(datei)
    return list(zeilen.values())


@login_required
def titel_view(request, titel):
    lied = get_object_or_404(Lied.objects.prefetch_related("solist", "dirigent"), id=titel)
    darf_aendern = request.user.has_perm("intern.change_lied")
    context = {
        "seitentitel": lied.titel,
        "lied": lied,
        "medien": _medien(lied, lied.ordner_id in visible_folder_ids(request.user)),
        "up": "titel_list",
        "edit": "titel_edit" if darf_aendern else None,
        "history": "titel_aenderungen" if darf_aendern else None,
        "id": titel,
    }
    # Keine Seiten-Dropzone: abgelegt wird nur über die Ablagefläche der
    # Medien-Karte (titel.html, nur mit `change_lied`).
    return render(request, "titel.html", context)


@permission_required("intern.change_lied", raise_exception=True)
def titel_edit(request, titel):
    lied = get_object_or_404(Lied, id=titel)

    if request.method == "POST":
        form = LiedEditForm(request.POST, request.FILES, instance=lied)
        if form.is_valid():
            instance = form.save(commit=False)
            instance._audit_user = request.user
            instance.save()
            form.save_m2m()
            if instance.titel != lied.titel:
                liedablage.titel_geaendert(instance, instance.titel)
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

    medien_dateien = _medien_dateien(lied)
    vergeben = {r["key"] for z in medien_dateien for r in z["rollen"]}
    context = {
        "form": form,
        "lied": lied,
        "seitentitel": f"bearbeiten: {lied.titel}",
        "view": "titel_view",
        "id": titel,
        "konzerte_count": konzerte_count,
        "can_delete": not blocking,
        "delete_tooltip": ("Kann nicht gelöscht werden: " + ", ".join(blocking)) if blocking else "",
        # Die Medien-Karte dieser Seite vergibt die Rollen von Hand.
        "medien_dateien": medien_dateien,
        "rollen": [{"key": r.key, "label": r.label} for r in liedrollen.ROLLEN],
        "freie_rollen": [
            {"key": r.key, "label": r.label}
            for r in liedrollen.ROLLEN
            if r.key not in vergeben
        ],
    }
    return render(request, "titel_edit.html", context)


@permission_required("intern.change_lied", raise_exception=True)
@require_POST
def titel_rolle(request, titel):
    """Die Rolle einer Datei des Lied-Ordners setzen, verschieben oder lösen.

    Die Rolle ist je Lied einmal vergeben: setzt man sie auf eine andere Datei,
    verliert die bisherige sie. Ohne `rolle` wird sie von dieser Datei gelöst."""
    lied = get_object_or_404(Lied, id=titel)
    rolle = (request.POST.get("rolle") or "").strip()
    if rolle and rolle not in liedrollen.LABELS:
        return JsonResponse({"status": "error", "message": "Unbekannte Rolle"}, status=400)
    datei = _datei_des_lieds(lied, request.POST.get("datei"))
    if datei is None and not rolle:
        # Lösen geht auch dort, wo die Datei nicht (mehr) im Lied-Ordner liegt —
        # sonst klebte eine solche Rolle für immer an ihr.
        zeile = LiedDatei.objects.filter(
            lied=lied, datei_id=_als_zahl(request.POST.get("datei"))
        ).select_related("datei").first()
        datei = zeile.datei if zeile else None
    if datei is None:
        return _fremde_datei()
    if rolle:
        liedablage.rolle_setzen(lied, rolle, datei, request.user)
    else:
        liedablage.rolle_entfernen(lied, datei, request.user)
    return JsonResponse({"status": "success", "rolle": rolle, "datei": datei.pk})


def _als_zahl(wert):
    wert = wert or ""
    return int(wert) if wert.isdigit() else None


def _datei_des_lieds(lied, datei_id):
    """Die Datei, sofern sie im Ordner dieses Liedes liegt — sonst ``None``."""
    datei_id = _als_zahl(datei_id)
    datei = File.objects.filter(pk=datei_id).first() if datei_id is not None else None
    if datei is None or lied.ordner_id is None or datei.folder_id != lied.ordner_id:
        return None
    return datei


def _fremde_datei():
    return JsonResponse(
        {"status": "error", "message": "Die Datei gehört nicht zu diesem Lied"}, status=400
    )


@permission_required("intern.change_lied", raise_exception=True)
@require_POST
def titel_datei(request, titel):
    """Eine Datei des Lied-Ordners umbenennen oder löschen (Medien-Karte der
    Bearbeiten-Seite).

    Das Lied besitzt seinen Ordner: wer das Lied ändern darf, darf dessen
    Dateien umbenennen und löschen, ohne Ordnerrecht — wie beim Hochladen.
    Außerhalb des Lied-Ordners gilt das nicht."""
    from .folders import _validate_rename

    lied = get_object_or_404(Lied, id=titel)
    datei = _datei_des_lieds(lied, request.POST.get("datei"))
    if datei is None:
        return _fremde_datei()
    # Ein Umbenennen erreicht jede verknüpfte Kopie — auch ein Profilbild.
    if not darf_avatar_aendern(request.user, datei):
        raise PermissionDenied
    aktion = request.POST.get("aktion")
    if aktion == "loeschen":
        # Erst die Rolle lösen: das Löschen der Datei nähme die Rollenzeile
        # sonst ohne Eintrag im Änderungsprotokoll mit.
        datei_pk = datei.pk
        liedablage.rolle_entfernen(lied, datei, request.user)
        dateiablage.datei_loeschen(datei)
        folders.invalidate()
        return JsonResponse({"status": "success", "datei": datei_pk})
    if aktion == "umbenennen":
        name = _validate_rename(request.POST.get("name"))
        if not name:
            return JsonResponse({"status": "error", "message": "Ungültiger Name."}, status=400)
        # Ein Name je Ordner: ist er schon vergeben, wird hier nicht verschmolzen
        # — das bleibt dem Dateibrowser mit seinem Dialog.
        status, _ = dateiablage.umbenennen(datei, name, request.user, {})
        if status != "ok":
            return JsonResponse(
                {"status": "error", "message": f"„{name}“ ist schon vergeben."}, status=409
            )
        return JsonResponse({"status": "success", "datei": datei.pk, "name": name})
    return JsonResponse({"status": "error", "message": "Unbekannte Aktion"}, status=400)


@permission_required("intern.delete_lied", raise_exception=True)
@require_POST
def titel_delete(request, titel):
    lied = get_object_or_404(Lied, id=titel)
    if lied.konzert_set.exists() or lied.solist.exists() or lied.dirigent.exists():
        return redirect("titel_edit", titel=titel)
    if lied.ordner_id:
        # Der Ordner gehört zum Lied: Er geht mit, samt rollenloser Dateien.
        from .folders import _delete_folder_deep

        ordner = Folder.objects.filter(pk=lied.ordner_id).first()
        if ordner is not None:
            _delete_folder_deep(ordner)
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