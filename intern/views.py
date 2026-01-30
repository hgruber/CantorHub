from datetime import date, datetime, datetime_CAPI

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from .models import Forum, Mitteilung


@login_required
def view(request, forum):
    """Render das Haupt‑Template mit den ersten 20 Nachrichten."""
    messages = Mitteilung.objects.filter(forum_id=forum)[:15]
    return render(request, "forum.html", {"messages": messages})


@login_required
def more(request):
    """Return älterer Nachrichten (30 Stück) als HTML‑Snippet."""
    # Wir brauchen die ID der ältesten geladenen Nachricht (Client‑seitig sendet `last_id`).
    last_id = request.GET.get("last_id")
    if last_id:
        queryset = Mitteilung.objects.filter(forum_id=146, id__lt=last_id)[:30]
    else:
        queryset = Mitteilung.objects.filter(forum_id=146)[:30]

    html = render_to_string("_messages.html", {"messages": queryset})
    return JsonResponse({"html": html})


@login_required
# @require_POST
def send(request):
    mitteilung = request.POST.get("mitteilung", "").strip()
    if mitteilung:
        msg = Mitteilung.objects.create(
            sender_id=2,
            forum_id=146,
            mitteilung=mitteilung,
            datum=datetime.now(),
        )
        # Render nur die *eine* neue Nachricht, um sie einzufügen.
        html = render_to_string("_message.html", {"message": msg})
        return JsonResponse({"html": html})
    return JsonResponse({"error": "Message is empty"}, status=400)
