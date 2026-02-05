from datetime import date, datetime, datetime_CAPI

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Max
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_POST

from .forms import RegisterForm
from .models import Forum, Mitteilung, User


def home(request):
    return render(request, "index.html")


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            try:
                user = User.objects.get(username=form.cleaned_data["username"])
                password = get_random_string(10)
                # user.set_password(password)
                subject = "Dein neues Passwort"
                message = f"""Du kannst Dich sofort im internen Bereich anmelden\nmit deinem Benutzer '{user.username}' und Deinem\nneuen Passwort: {password}"""
                from_email = "webmaster@example.org"
                recipient_list = [user.email]
                send_mail(subject, message, from_email, recipient_list)
                return redirect("register_success")
            except User.DoesNotExist:
                form.add_error(None, "Benutzer existiert nicht")
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})


def register_success(request):
    return render(request, "register_success.html")


@login_required
def foren(request):
    foren = Forum.objects.extra_data().order_by("-zugriff")
    return render(request, "foren.html", {"seitentitel": "Foren", "foren": foren})


@login_required
def view(request, forum):
    messages = Mitteilung.objects.filter(forum_id=forum)[:25]
    last_id = max(msg.id for msg in messages)
    oldest_id = min(msg.id for msg in messages)
    return render(
        request,
        "forum.html",
        {
            "seitentitel": f"Forum: {Forum.objects.get(id=forum).thema}",
            "forum": forum,
            "last_id": last_id,
            "oldest_id": oldest_id,
            "messages": messages,
        },
    )


@login_required
def poll(request, forum, last_id=0):
    if last_id == 0:
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
    oldest_id = request.GET.get("oldest_id", 0)
    last_id = request.GET.get("last_id", 0)
    print(f"more: {last_id} - {oldest_id}")
    messages = Mitteilung.objects.filter(forum_id=forum, id__lt=oldest_id)
    return render(
        request,
        "_messages.html",
        {
            "forum": forum,
            "last_id": last_id,
            "oldest_id": oldest_id,
            "messages": messages,
        },
    )


@login_required
@require_POST
def send(request, forum):
    mitteilung = request.POST.get("mitteilung", "").strip()
    last_id = request.POST.get("last_id", 0)
    if mitteilung:
        Mitteilung.objects.create(
            sender_id=request.user.id,
            forum_id=forum,
            mitteilung=mitteilung,
            datum=datetime.now(),
        )
    return poll(request, forum, last_id)
