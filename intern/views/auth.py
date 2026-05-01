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


def _find_user(username, email, first_name, last_name):
    """Look up a user by username, email, or first+last name."""
    if username:
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            return None
    if email:
        try:
            return User.objects.get(email=email)
        except User.DoesNotExist:
            return None
    if first_name and last_name:
        try:
            return User.objects.get(first_name=first_name, last_name=last_name)
        except User.DoesNotExist:
            return None
    return None


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = _find_user(
                cd.get("username"),
                cd.get("email"),
                cd.get("first_name"),
                cd.get("last_name"),
            )
            if user and user.email:
                password = get_random_string(10)
                user.set_password(password)
                user.save()
                subject = "Dein neues Passwort"
                message = (
                    f"Du kannst Dich sofort im internen Bereich anmelden\n"
                    f"mit deinem Benutzer '{user.username}' und Deinem\n"
                    f"neuen Passwort: {password}"
                )
                send_mail(subject, message, None, [user.email])
                return redirect("register_success")
            else:
                form.add_error(
                    None,
                    "Benutzer nicht gefunden oder keine E-Mail-Adresse hinterlegt.",
                )
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})


def register_success(request):
    return render(request, "register_success.html")