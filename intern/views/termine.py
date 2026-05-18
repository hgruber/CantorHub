import io

import secrets
from datetime import date, datetime, timedelta

from django.conf import settings
from django.utils.timezone import now as timezone_now
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_tables2 import RequestConfig
from icalendar import Calendar, Event
from odf.opendocument import OpenDocumentText
from odf.style import ParagraphProperties, Style, TextProperties
from odf.text import P
from odf.namespaces import FONS

from intern import folders

from ..forms import TerminForm
from ..models import Konzert, Lied, Ort, Termin, User, Zusage
from ..tables import TerminTabelle

__all__ = [
    "termin_list",
    "termin_view",
    "termin_zusage",
    "termin_edit",
    "termin_add",
    "calendar_ics",
    "konzert_odt",
]

ZUSAGE_TRANSITIONS = {
    "": ["1", "2", "3"],
    "3": ["1", "2"],
    "1": [],
    "2": ["1", "3"],
}


def _build_stimme_groups(termin):
    STIMMEN_ORDER = ["S", "A", "T", "B", "C", "M"]
    STIMMEN_LABELS = {"S": "Sopran", "A": "Alt", "T": "Tenor", "B": "Bass", "C": "Chorleiter", "M": "Musiker"}
    active_users = User.objects.filter(is_active=True).order_by("last_name", "first_name")
    zusagen = {z.person_id: z.option for z in Zusage.objects.filter(termin=termin)}
    groups = []
    for stimme in STIMMEN_ORDER:
        users = [u for u in active_users if u.stimme == stimme]
        if not users:
            continue
        g = {"1": [], "2": [], "3": [], "": []}
        for u in users:
            g[zusagen.get(u.id, "")].append(u)
        groups.append({
            "key": stimme, "label": STIMMEN_LABELS[stimme],
            "zusagen": g["1"], "absagen": g["2"],
            "vielleicht": g["3"], "keine_angabe": g[""],
        })
    return groups


def calendar_ics(request, secret):
    if not secrets.compare_digest(secret, settings.ICAL_SECRET):
        from django.http import Http404
        raise Http404
    cutoff = timezone_now() - timedelta(days=180)
    termine = Termin.objects.filter(datum__gte=cutoff).select_related("ort").order_by("datum")
    cal = Calendar()
    cal.add("prodid", "-//CantorHub//DE")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "CantorHub")
    for t in termine:
        ev = Event()
        ev.add("uid", f"termin-{t.pk}@cantorhub")
        ev.add("summary", t.kurz)
        ev.add("dtstart", t.datum)
        ev.add("dtend", t.datum_bis or t.datum + timedelta(hours=2))
        if t.lang:
            ev.add("description", t.lang)
        if t.ort:
            parts = [t.ort.name, t.ort.strasse, f"{t.ort.plz or ''} {t.ort.ort or ''}".strip()]
            ev.add("location", ", ".join(p for p in parts if p))
            if t.ort.breite is not None and t.ort.laenge is not None:
                ev.add("geo", (t.ort.breite, t.ort.laenge))
        cal.add_component(ev)
    return HttpResponse(cal.to_ical(), content_type="text/calendar; charset=utf-8")


@login_required
def termin_list(request):
    past = request.GET.get("past") == "1"
    annotations = {
        "anwesenheit_option": Coalesce(
            Subquery(
                Zusage.objects.filter(
                    termin=OuterRef("pk"), person=request.user
                ).values("option")[:1]
            ),
            Value(""),
        ),
        "anzahl_songs": Count("konzert", distinct=True),
        "anzahl_zusagen_sopran": Count(
            "zusage",
            filter=Q(zusage__person__stimme="S", zusage__option="1"),
            distinct=True,
        ),
        "anzahl_zusagen_alt": Count(
            "zusage",
            filter=Q(zusage__person__stimme="A", zusage__option="1"),
            distinct=True,
        ),
        "anzahl_zusagen_tenor": Count(
            "zusage",
            filter=Q(zusage__person__stimme="T", zusage__option="1"),
            distinct=True,
        ),
        "anzahl_zusagen_bass": Count(
            "zusage",
            filter=Q(zusage__person__stimme="B", zusage__option="1"),
            distinct=True,
        ),
        "anzahl_vielleicht": Count(
            "zusage",
            filter=Q(zusage__option="3"),
            distinct=True,
        ),
        "anzahl_absagen": Count(
            "zusage",
            filter=Q(zusage__option="2"),
            distinct=True,
        ),
        "anzahl_keine_angabe": Coalesce(
            Value(
                User.objects.filter(is_active=True).count(),
                output_field=IntegerField(),
            ) - Count("zusage", distinct=True),
            Value(0),
            output_field=IntegerField(),
        ),
    }
    if past:
        qs = Termin.objects.filter(datum__lte=timezone_now()).order_by("-datum")
    else:
        qs = Termin.objects.filter(datum__gt=timezone_now()).order_by("datum")
    termin_queryset = qs.annotate(**annotations)

    table = TerminTabelle(termin_queryset)
    RequestConfig(request, paginate=False).configure(table)
    from django.urls import reverse

    ical_path = reverse("calendar_ics", args=[settings.ICAL_SECRET])
    ical_url = request.build_absolute_uri(ical_path)
    webcal_url = "webcal://" + request.get_host() + ical_path
    add = "termin_add" if request.user.has_perm("intern.add_termin") else None
    return render(
        request,
        "table.html",
        {
            "table": table,
            "seitentitel": "Vergangene Termine" if past else "Termine",
            "ical_url": ical_url,
            "webcal_url": webcal_url,
            "upload_folder_id": folders.termine(),
            "add": add,
            "add_form": TerminForm() if request.user.has_perm("intern.add_termin") else None,
            "add_label": "Neuer Termin",
            "past": past,
        },
    )


@login_required
def termin_view(request, id):
    termin = get_object_or_404(Termin.objects.select_related("ort"), id=id)
    lieder = Konzert.objects.filter(termin=termin).select_related("lied").order_by("position")
    my_zusage = Zusage.objects.filter(termin=termin, person=request.user).order_by("-id").first()
    my_option = my_zusage.option if my_zusage else ""
    context = {
        "seitentitel": str(termin),
        "termin": termin,
        "stimme_groups": _build_stimme_groups(termin),
        "my_option": my_option,
        "lieder": lieder,
        "up": "termin_list",
        "edit": "termin_edit",
        "id": id,
    }
    return render(request, "termin.html", context)


@login_required
def konzert_odt(request, id):
    termin = get_object_or_404(Termin, id=id)
    lieder = Konzert.objects.filter(termin=termin).select_related("lied").order_by("position")

    doc = OpenDocumentText()

    def _add_style(name, font_size, bold=False, align=None):
        style = Style(name=name, family="paragraph")
        tp = TextProperties()
        tp.setAttrNS(FONS, "font-name", "Sans Serif")
        tp.setAttrNS(FONS, "font-size", font_size)
        if bold:
            tp.setAttrNS(FONS, "font-weight", "bold")
        style.addElement(tp)
        if align:
            pp = ParagraphProperties()
            pp.setAttrNS(FONS, "text-align", align)
            style.addElement(pp)
        doc.styles.addElement(style)

    _add_style("Titel", "18pt", bold=True, align="center")
    _add_style("Item", "14pt")
    _add_style("Composer", "10pt", align="right")

    doc.text.addElement(P(text=str(termin), stylename="Titel"))

    for k in lieder:
        if k.lied:
            doc.text.addElement(P(text=k.lied.titel, stylename="Item"))
            if k.lied.komponist:
                doc.text.addElement(P(text=k.lied.komponist, stylename="Composer"))

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    safe_name = termin.kurz.replace('"', "")
    return FileResponse(buf, as_attachment=True, filename=f"{safe_name}.odt", content_type="application/vnd.oasis.opendocument.text")


@login_required
@require_POST
def termin_zusage(request, id):
    termin = get_object_or_404(Termin, id=id)
    if not termin.anwesenheit:
        if not request.headers.get("HX-Request"):
            return redirect("termin_view", id=id)
        return render(request, "_termin_zusage.html", {
            "termin": termin,
            "my_option": "",
            "stimme_groups": [],
        })
    new_option = request.POST.get("option", "")
    current = Zusage.objects.filter(termin=termin, person=request.user).order_by("-id").first()
    current_option = current.option if current else ""

    if new_option in ZUSAGE_TRANSITIONS.get(current_option, []):
        Zusage.objects.update_or_create(
            person=request.user, termin=termin,
            defaults={"option": new_option},
        )
        current_option = new_option

    if not request.headers.get("HX-Request"):
        return redirect("termin_view", id=id)

    return render(request, "_termin_zusage.html", {
        "termin": termin,
        "my_option": current_option,
        "stimme_groups": _build_stimme_groups(termin),
    })


@permission_required("intern.change_termin", raise_exception=True)
def termin_edit(request, id):
    termin = get_object_or_404(Termin, id=id)

    if request.method == "POST":
        form = TerminForm(request.POST, instance=termin)
        if form.is_valid():
            form.save()
            return redirect("termin_view", id=id)
    else:
        form = TerminForm(instance=termin)

    context = {
        "form": form,
        "termin": termin,
        "seitentitel": f"bearbeiten: {termin.kurz}",
        "view": "termin_view",
        "id": id,
    }
    return render(request, "termin_edit.html", context)


@permission_required("intern.add_termin", raise_exception=True)
def termin_add(request):
    if request.method == "POST":
        form = TerminForm(request.POST)
        if form.is_valid():
            termin = form.save()
            return redirect("termin_view", id=termin.id)
    else:
        form = TerminForm()
    context = {
        "form": form,
        "seitentitel": "Neuer Termin",
    }
    return render(request, "termin_edit.html", context)