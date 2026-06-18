import logging
import threading

from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from intern import ejabberd
from intern.app_settings import (
    get_config_int,
    get_from_email,
    is_ejabberd_configured,
)
from intern.mail import send_branded_mail

from ..forms import MitgliedBeitrittForm, RegisterForm
from ..models import User

__all__ = [
    "CantorLoginView",
    "CantorPasswordResetConfirmView",
    "custom_400",
    "custom_403",
    "custom_404",
    "custom_500",
    "datenschutz",
    "home",
    "make_invite_token",
    "mitglied_beitritt",
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
        if is_ejabberd_configured() and not user.xmpp:
            password = form.cleaned_data["password"]
            threading.Thread(
                target=_provision_xmpp_user,
                args=(user.pk, password),
                daemon=True,
            ).start()
        return response


def home(request):
    return render(request, "index.html")


def datenschutz(request):
    vorstand = (
        User.objects.filter(groups__name="Vorstand", is_active=True)
        .order_by("last_name", "first_name")
    )
    return render(request, "datenschutz.html", {
        "vorstand": vorstand,
        "kontakt_email": get_from_email(),
    })


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
                send_branded_mail(
                    subject,
                    user.email,
                    "emails/password_reset.html",
                    {"user": user, "link": link},
                    text_body=message,
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
        if is_ejabberd_configured() and user.xmpp:
            localpart = user.xmpp.split("@")[0]
            threading.Thread(
                target=ejabberd.set_user_password,
                args=(localpart, form.cleaned_data["new_password1"]),
                daemon=True,
            ).start()
        return response


def register_success(request):
    return render(request, "register_success.html")


# ---------------------------------------------------------------------------
# Mitglieds-Beitritt (öffentliches Antragsformular hinter signiertem Link)
# ---------------------------------------------------------------------------

INVITE_MAX_AGE = 7 * 24 * 3600  # 7 Tage
_invite_signer = TimestampSigner(salt="intern.mitglied_invite")


def make_invite_token(email):
    """Signierter, 7 Tage gültiger Token, der die eingeladene E-Mail trägt."""
    return _invite_signer.sign(email)


def _read_invite_token(token):
    """E-Mail aus einem gültigen Token, sonst None (ungültig/abgelaufen)."""
    try:
        return _invite_signer.unsign(token, max_age=INVITE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def _member_managers():
    """Aktive Benutzer mit der Berechtigung, Mitglieder zu verwalten."""
    return User.objects.filter(
        Q(is_superuser=True)
        | Q(groups__permissions__codename="change_user")
        | Q(user_permissions__codename="change_user"),
        is_active=True,
    ).distinct()


def mitglied_beitritt(request, token):
    """Öffentliches Beitritts-Formular hinter einem signierten Einladungs-Link.

    Legt bei erfolgreichem Absenden ein *inaktives* Mitglied an, schickt eine
    Bestätigung an den Antragsteller, benachrichtigt die Mitglieder-Verwalter
    und protokolliert den Vorgang als „Neuer Mitgliedsantrag".
    """
    email = _read_invite_token(token)
    if not email:
        return render(request, "mitglied_beitritt_invalid.html", status=400)

    if request.method == "POST":
        form = MitgliedBeitrittForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = email
            user.is_active = False
            user._audit_user = user
            user._audit_application = True
            user.save()
            form.save_m2m()

            send_branded_mail(
                "Dein Mitgliedsantrag bei Just Gospel Frankfurt",
                email,
                "emails/mitglied_beitritt_success.html",
                {"user": user},
                text_body=(
                    f"Hallo {user.first_name},\n\n"
                    f"vielen Dank für Deinen Mitgliedsantrag. Wir haben ihn erhalten.\n"
                    f"Über die Aufnahme entscheidet der Vorstand — Du erhältst dann\n"
                    f"eine weitere Nachricht.\n\n"
                    f"Dein gewünschter Benutzername: {user.username}"
                ),
            )

            managers = [u.email for u in _member_managers() if u.email]
            if managers:
                link = request.build_absolute_uri(
                    reverse("mitglied_view", args=[user.id])
                )
                send_branded_mail(
                    "Neuer Mitgliedsantrag",
                    managers,
                    "emails/mitglied_antrag_admin.html",
                    {"applicant": user, "link": link},
                    text_body=(
                        f"Es liegt ein neuer Mitgliedsantrag vor:\n\n"
                        f"{user.first_name} {user.last_name} ({email})\n\n"
                        f"Details: {link}"
                    ),
                )
            return render(request, "mitglied_beitritt_success.html", {"user": user})
    else:
        form = MitgliedBeitrittForm()

    return render(request, "mitglied_beitritt.html", {"form": form, "email": email})


def custom_400(request, exception):
    return render(request, "400.html", status=400)


def custom_403(request, exception):
    return render(request, "403.html", status=403)


def custom_404(request, exception):
    return render(request, "404.html", status=404)


def custom_500(request):
    return render(request, "500.html", status=500)