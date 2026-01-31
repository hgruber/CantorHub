from datetime import date, datetime, datetime_CAPI

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from .models import Forum, Mitteilung


def home(request):
    return render(request, "index.html")


@login_required
def foren(request):
    return render(request, "foren.html", {"seitentitel": "Foren"})


@login_required
def view(request, forum):
    messages = Mitteilung.objects.filter(forum_id=forum)[:15]
    last_id = max(msg.id for msg in messages)
    return render(
        request,
        "forum.html",
        {
            "seitentitel": f"Forum: {Forum.objects.get(id=forum).thema}",
            "forum": forum,
            "last_id": last_id,
            "messages": messages,
        },
    )


@login_required
def poll(request, forum):
    last_id = request.GET.get("last_id", 0)
    messages = Mitteilung.objects.filter(forum_id=forum, id__gt=last_id)
    if messages:
        last_id = max(msg.id for msg in messages)
    return render(
        request,
        "_messages.html",
        {"forum": forum, "last_id": last_id, "messages": messages},
    )


@login_required
def more(request, forum):
    """Return älterer Nachrichten (30 Stück) als HTML‑Snippet."""
    # Wir brauchen die ID der ältesten geladenen Nachricht (Client‑seitig sendet `last_id`).
    last_id = request.GET.get("last_id")
    if last_id:
        queryset = Mitteilung.objects.filter(forum_id=forum, id__lt=last_id)[:30]
    else:
        queryset = Mitteilung.objects.filter(forum_id=forum)[:30]
    return render(request, "_messages.html", {"forum": forum, "messages": queryset})


@login_required
@require_POST
def send(request, forum):
    mitteilung = request.POST.get("mitteilung", "").strip()
    if mitteilung:
        msg = Mitteilung(
            sender_id=request.user.id,
            forum_id=forum,
            mitteilung=mitteilung,
            datum=datetime.now(),
        )
        msg.save()
        return render(
            request,
            "_message.html",
            {
                "message": msg,
            },
        )
    return HttpResponse(status=404)
