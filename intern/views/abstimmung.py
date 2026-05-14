from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from intern.replacements import parse_abstimmung_directive, render_abstimmung

from ..models import Abstimmung, Artikel

__all__ = ["abstimmung_vote"]


@login_required
@require_POST
def abstimmung_vote(request):
    seite = request.POST.get("seite", "")
    titel = request.POST.get("titel", "")
    action = request.POST.get("action", "vote")

    artikel = Artikel.objects.filter(name=seite).order_by("-version").first()
    if not artikel:
        raise Http404("Artikel nicht gefunden")

    parsed = parse_abstimmung_directive(artikel.text, titel)
    if not parsed:
        raise Http404("Abstimmung nicht gefunden")
    max_stimmen, options, deadline = parsed

    key = f"{seite}:{titel}"
    locked = bool(deadline and date.today() > deadline)

    if action == "vote" and not locked:
        selected = [o for o in request.POST.getlist("option") if o in options]
        if max_stimmen > 0:
            selected = selected[:max_stimmen]
        Abstimmung.objects.filter(abstimmung=key, person=request.user).delete()
        Abstimmung.objects.bulk_create(
            [
                Abstimmung(abstimmung=key, person=request.user, option=opt)
                for opt in selected
            ]
        )

    show_results = request.POST.get("show_results") == "1"

    if not request.headers.get("HX-Request"):
        return redirect("article_view", name=seite)

    html = render_abstimmung(
        request, seite, titel, max_stimmen, options, deadline, show_results
    )
    return HttpResponse(html)
