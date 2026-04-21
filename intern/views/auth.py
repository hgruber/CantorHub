import logging
import threading

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.utils.crypto import get_random_string

from intern import ejabberd

from ..forms import RegisterForm
from ..models import User

__all__ = [
    "CantorLoginView",
    "home",
    "register",
    "register_success",
]

logger = logging.getLogger(__name__)


def _provision_xmpp_user(user_pk, password):
    """Create an ejabberd account for a user and set their vCard. Runs in a daemon thread."""
    try:
        user = User.objects.get(pk=user_pk)
    except User.DoesNotExist:
        return

    if user.xmpp:
        return

    jid = ejabberd.register_user(user.username, password)
    if not jid:
        return

    User.objects.filter(pk=user_pk).update(xmpp=jid)

    full_name = f"{user.first_name} {user.last_name}".strip() or user.username
    localpart = jid.split("@")[0]
    ejabberd.set_vcard(localpart, full_name, avatar_file=user.avatar)


class CantorLoginView(auth_views.LoginView):
    """Login view that provisions ejabberd accounts on first login."""

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.get_user()
        if settings.EJABBERD_ENABLED and not user.xmpp:
            password = form.cleaned_data["password"]
            threading.Thread(
                target=_provision_xmpp_user,
                args=(user.pk, password),
                daemon=True,
            ).start()
        return response


def home(request):
    return render(request, "index.html")


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            try:
                user = User.objects.get(username=form.cleaned_data["username"])
                password = get_random_string(10)
                user.set_password(password)
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