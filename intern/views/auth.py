import logging
import threading

from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from intern import ejabberd
from intern.app_settings import (
    get_config_bool,
    get_config_int,
    get_from_email,
    is_email_configured,
)

from ..forms import RegisterForm
from ..models import User

__all__ = [
    "CantorLoginView",
    "CantorPasswordResetConfirmView",
    "custom_400",
    "custom_403",
    "custom_404",
    "custom_500",
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
        if get_config_bool("EJABBERD_ENABLED") and not user.xmpp:
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


def _client_ip(request):
    """Client-IP hinter nginx: letzter Eintrag in X-Forwarded-For (von nginx
    angehängt, nicht spoofbar), sonst REMOTE_ADDR."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def register(request):
    """Passwort-zurücksetzen-Anfrage.

    Setzt das Passwort nicht direkt, sondern verschickt einen Bestätigungslink
    (Django-Token). Antwortet unabhängig vom Treffer mit derselben neutralen
    Meldung, damit keine Konten enumeriert werden können, und drosselt pro IP.
    """
    if request.method == "POST":
        form = RegisterForm(request.POST)

        throttle_key = f"pwreset-throttle:{_client_ip(request)}"
        attempts = cache.get(throttle_key, 0)
        if attempts >= get_config_int("PWRESET_MAX_PER_HOUR", 5):
            form.add_error(
                None, "Zu viele Anfragen. Bitte versuche es später erneut."
            )
            return render(request, "register.html", {"form": form})

        if form.is_valid():
            cache.set(throttle_key, attempts + 1, 3600)
            cd = form.cleaned_data
            user = _find_user(
                cd.get("username"),
                cd.get("email"),
                cd.get("first_name"),
                cd.get("last_name"),
            )
            if user and user.email and user.is_active:
                uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                link = request.build_absolute_uri(
                    reverse("password_reset_confirm", args=[uidb64, token])
                )
                subject = "Passwort zurücksetzen"
                message = (
                    f"Hallo {user.first_name},\n\n"
                    f"über diesen Link kannst Du ein neues Passwort für Deinen\n"
                    f"Benutzer '{user.username}' setzen:\n\n{link}\n\n"
                    f"Wenn Du das nicht angefordert hast, kannst Du diese E-Mail\n"
                    f"ignorieren — Dein Passwort bleibt unverändert."
                )
                try:
                    send_mail(subject, message, get_from_email(), [user.email])
                except Exception:
                    logger.exception("Failed to send password reset email to %s", user.email)
                if not is_email_configured():
                    logger.warning(
                        "EMAIL_HOST is not set in Konfiguration — email was written to console, not sent."
                    )
                logger.info("Password reset link sent to %s for user %s", user.email, user.username)
            # Immer dieselbe Antwort — kein Rückschluss auf existierende Konten.
            return redirect("register_success")
    else:
        form = RegisterForm()
    return render(request, "register.html", {"form": form})


class PasswordResetForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].widget.attrs.update(
            {"class": "password-field", "id": "new_password1"}
        )
        self.fields["new_password2"].widget.attrs.update({"id": "new_password2"})


class CantorPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """Setzt das Passwort nach Klick auf den E-Mail-Link.

    Synchronisiert das neue Passwort anschließend zu ejabberd, wie es auch
    mitglied_passwd tut.
    """

    template_name = "reset_confirm.html"
    success_url = reverse_lazy("login")
    form_class = PasswordResetForm

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        if get_config_bool("EJABBERD_ENABLED") and user.xmpp:
            localpart = user.xmpp.split("@")[0]
            threading.Thread(
                target=ejabberd.set_user_password,
                args=(localpart, form.cleaned_data["new_password1"]),
                daemon=True,
            ).start()
        return response


def register_success(request):
    return render(request, "register_success.html")


def custom_400(request, exception):
    return render(request, "400.html", status=400)


def custom_403(request, exception):
    return render(request, "403.html", status=403)


def custom_404(request, exception):
    return render(request, "404.html", status=404)


def custom_500(request):
    return render(request, "500.html", status=500)