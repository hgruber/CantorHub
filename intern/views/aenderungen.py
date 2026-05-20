"""
Views for the ChangeLog audit trail — per-object change history.
"""

from itertools import chain

from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django_tables2 import RequestConfig

from ..models import ChangeLog, Forum, Lied, Ort, Termin, Zusage
from ..models import User as MitgliedUser

__all__ = [
    "aenderungsprotokoll_list",
    "termin_aenderungen",
    "mitglied_aenderungen",
    "titel_aenderungen",
    "ort_aenderungen",
    "forum_aenderungen",
]

# Human-readable field labels for display
FIELD_LABELS = {
    # User
    "first_name": "Vorname",
    "last_name": "Nachname",
    "stimme": "Stimme",
    "is_active": "Aktiv",
    "email": "E-Mail",
    "xmpp": "XMPP",
    "strasse": "Straße",
    "plz": "PLZ",
    "ort": "Ort",
    "telefon": "Telefon",
    "telefon_mobil": "Mobil",
    "geburtstag": "Geburtstag",
    "avatar_id": "Avatar",
    # Termin
    "kurz": "Kurzbezeichnung",
    "datum": "Datum",
    "datum_bis": "Datum bis",
    "lang": "Beschreibung",
    "ort_id": "Veranstaltungsort",
    "anwesenheit": "Anwesenheit",
    "repertoire": "Repertoire",
    # Lied
    "titel": "Titel",
    "aktiv": "Aktiv",
    "tempo": "Tempo",
    "beats": "Beats",
    "hymne": "Hymne",
    "acapella": "A cappella",
    "weihnacht": "Weihnachten",
    "komponist": "Komponist",
    "original_id": "Original",
    "aufnahme_id": "Aufnahme",
    "pdf_id": "PDF",
    "noten_id": "Noten",
    # Zusage
    "option": "Antwort",
    # Forum
    "thema": "Thema",
    "bild_id": "Bild",
    # Konzert
    "setlist": "Ablauf",
    # Ort
    "name": "Name",
    "beschreibung": "Beschreibung",
    "breite": "Breitengrad",
    "laenge": "Längengrad",
}

# Fields whose values are filer File PKs — resolved to filenames at display time
_FILE_ID_FIELDS = {"avatar_id", "original_id", "aufnahme_id", "pdf_id", "noten_id", "bild_id"}

# FK fields that should be resolved to a human-readable name: field -> (Model, label_attr)
_FK_RESOLVE = {
    "ort_id": (Ort, None),  # None means use str()
}


_OPTION_LABELS = {"1": "Zusage", "2": "Absage", "3": "Eventuell", "None": "Keine Angabe", None: "Keine Angabe", "": "Keine Angabe"}

_VALUE_TRANSLATIONS = {
    ("Zusage", "option"): _OPTION_LABELS,
}

MODEL_LABELS = {
    "Termin": "Termin",
    "Zusage": "Anwesenheit",
    "Konzert": "Ablauf",
    "Lied": "Lied",
    "User": "Mitglied",
    "Forum": "Forum",
    "Ort": "Ort",
}


def _translate(model_name, field, value):
    table = _VALUE_TRANSLATIONS.get((model_name, field))
    if table is not None:
        return table.get(value, value)
    return value


def _annotate_entries(entries):
    """Attach change_rows, model_label, resolve stale Zusage reprs, and resolve file IDs."""
    from filer.models import File as FilerFile

    # Batch-resolve any Zusage entries whose object_repr was stored before __str__ existed
    zusage_ids = [e.object_id for e in entries if e.model_name == "Zusage" and "object" in (e.object_repr or "")]
    if zusage_ids:
        zusage_map = {z.pk: str(z) for z in Zusage.objects.filter(pk__in=zusage_ids).select_related("person")}
        for entry in entries:
            if entry.model_name == "Zusage" and entry.object_id in zusage_map:
                entry.object_repr = zusage_map[entry.object_id]

    # Collect all filer File IDs referenced in file-type fields across all entries
    file_ids = set()
    for entry in entries:
        for field, values in entry.changes.items():
            if field in _FILE_ID_FIELDS:
                for v in values:
                    if v and v != "None":
                        try:
                            file_ids.add(int(v))
                        except (ValueError, TypeError):
                            pass
    file_map = {f.pk: f.original_filename or f.name or f"#{f.pk}"
                for f in FilerFile.objects.filter(pk__in=file_ids)} if file_ids else {}

    # Batch-resolve generic FK fields (e.g. ort_id → Ort.name)
    fk_maps = {}  # field -> {pk: label}
    for field, (Model, _) in _FK_RESOLVE.items():
        ids = set()
        for entry in entries:
            for k, values in entry.changes.items():
                if k == field:
                    for v in values:
                        if v and v != "None":
                            try:
                                ids.add(int(v))
                            except (ValueError, TypeError):
                                pass
        if ids:
            fk_maps[field] = {obj.pk: str(obj) for obj in Model.objects.filter(pk__in=ids)}

    def _resolve_file(field, value):
        if field in _FK_RESOLVE:
            if not value or value == "None":
                return None
            try:
                return fk_maps.get(field, {}).get(int(value), value)
            except (ValueError, TypeError):
                return value
        if field not in _FILE_ID_FIELDS:
            return value
        if not value or value == "None":
            return None
        try:
            return file_map.get(int(value), value)
        except (ValueError, TypeError):
            return value

    for entry in entries:
        entry.change_rows = [
            (FIELD_LABELS.get(k, k),
             _resolve_file(k, _translate(entry.model_name, k, v[0])),
             _resolve_file(k, _translate(entry.model_name, k, v[1])))
            for k, v in entry.changes.items()
        ]
        entry.model_label = MODEL_LABELS.get(entry.model_name, entry.model_name)
    return entries


def _render_aenderungen(request, entries, obj_repr, back_url):
    _annotate_entries(entries)
    return render(request, "aenderungen.html", {
        "seitentitel": f"Änderungen: {obj_repr}",
        "entries": entries,
        "back_url": back_url,
    })


@login_required
@permission_required("intern.change_termin", raise_exception=True)
def termin_aenderungen(request, id):
    obj = get_object_or_404(Termin, id=id)
    termin_entries = ChangeLog.objects.filter(
        model_name="Termin", object_id=id
    ).select_related("user")
    zusage_pks = Zusage.objects.filter(termin_id=id).values_list("pk", flat=True)
    zusage_entries = ChangeLog.objects.filter(
        model_name="Zusage", object_id__in=zusage_pks
    ).select_related("user")
    konzert_entries = ChangeLog.objects.filter(
        model_name="Konzert", object_id=id
    ).select_related("user")
    entries = sorted(chain(termin_entries, zusage_entries, konzert_entries), key=lambda e: e.timestamp, reverse=True)
    return _render_aenderungen(request, entries, str(obj), reverse("termin_view", args=[id]))


@login_required
@permission_required("intern.change_user", raise_exception=True)
def mitglied_aenderungen(request, id):
    obj = get_object_or_404(MitgliedUser, id=id)
    entries = list(ChangeLog.objects.filter(model_name="User", object_id=id).select_related("user").order_by("-timestamp"))
    return _render_aenderungen(request, entries, str(obj), reverse("mitglied_view", args=[id]))


@login_required
@permission_required("intern.change_lied", raise_exception=True)
def titel_aenderungen(request, id):
    obj = get_object_or_404(Lied, id=id)
    entries = list(ChangeLog.objects.filter(model_name="Lied", object_id=id).select_related("user").order_by("-timestamp"))
    return _render_aenderungen(request, entries, str(obj), reverse("titel_view", args=[id]))


@login_required
@permission_required("intern.change_ort", raise_exception=True)
def ort_aenderungen(request, id):
    obj = get_object_or_404(Ort, id=id)
    entries = list(ChangeLog.objects.filter(model_name="Ort", object_id=id).select_related("user").order_by("-timestamp"))
    return _render_aenderungen(request, entries, str(obj), reverse("ort_view", args=[id]))


@login_required
@permission_required("intern.change_forum", raise_exception=True)
def forum_aenderungen(request, id):
    obj = get_object_or_404(Forum, id=id)
    entries = list(ChangeLog.objects.filter(model_name="Forum", object_id=id).select_related("user").order_by("-timestamp"))
    return _render_aenderungen(request, entries, str(obj), reverse("forum_view", args=[id]))


PAGE_SIZE = 25

_TOPBAR_ICON = (
    '<svg class="topbar-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"'
    ' fill="none" stroke="currentColor" stroke-width="2"'
    ' stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="10"/>'
    '<polyline points="12 6 12 12 16 14"/>'
    "</svg>"
)


@login_required
def aenderungsprotokoll_list(request):
    from ..tables import ChangeLogFilter

    if not request.user.is_superuser:
        return redirect("article_view", name="Aktuell")

    qs = ChangeLog.objects.select_related("user").order_by("-timestamp")
    f = ChangeLogFilter(request.GET, queryset=qs)

    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0

    page_qs = f.qs[offset : offset + PAGE_SIZE + 1]
    entries = list(page_qs)
    has_more = len(entries) > PAGE_SIZE
    if has_more:
        entries = entries[:PAGE_SIZE]
    _annotate_entries(entries)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        html = render_to_string(
            "aenderungsprotokoll_rows.html",
            {"entries": entries},
            request=request,
        )
        return JsonResponse({
            "html": html,
            "has_more": has_more,
            "next_offset": offset + PAGE_SIZE,
        })

    return render(request, "aenderungsprotokoll_list.html", {
        "entries": entries,
        "filter": f,
        "showfilter": True,
        "has_more": has_more,
        "next_offset": offset + PAGE_SIZE,
        "seitentitel": "Änderungsprotokoll",
        "topbar_icon": _TOPBAR_ICON,
    })
