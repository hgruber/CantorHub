import logging
import threading
from datetime import datetime
from io import BytesIO

from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.timezone import now as tz_now
from filer.models import File as FilerFile, Folder
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas

from intern import ejabberd
from intern.app_settings import (
    get_config,
    get_config_int,
    get_from_email,
    get_vereinsname,
    is_ejabberd_configured,
)
from intern.mail import format_config_mail, send_branded_mail

from ..forms import MitgliedBeitrittForm, MitgliedBestaetigungForm, RegisterForm
from ..models import Termin, User

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
    "mitglied_bestaetigung",
    "register",
    "register_success",
    "send_bestaetigung_mail",
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


def _save_antrag_pdf(user, email):
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    _, h = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, h - 2 * cm, f"Mitgliedsantrag - {get_vereinsname()}")
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, h - 2.8 * cm, f"Eingereicht am: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

    felder = [
        ("Vorname",      user.first_name),
        ("Nachname",     user.last_name),
        ("Benutzername", user.username),
        ("E-Mail",       email),
        ("Geburtsdatum", str(user.geburtstag) if user.geburtstag else ""),
        ("Stimmlage",    user.stimme),
        ("Strasse",      user.strasse or ""),
        ("PLZ / Ort",    f"{user.plz or ''} {user.ort or ''}".strip()),
        ("Telefon",      user.telefon or ""),
        ("Mobil",        user.telefon_mobil or ""),
    ]

    y = h - 4 * cm
    for label, wert in felder:
        if not wert:
            continue
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2 * cm, y, f"{label}:")
        c.setFont("Helvetica", 10)
        c.drawString(6 * cm, y, wert)
        y -= 0.65 * cm

    y -= 0.4 * cm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, y, "Einwilligungen (alle bestaetigt):")
    y -= 0.65 * cm
    c.setFont("Helvetica", 10)
    for text in ["Datenschutzerklaerung", "Datenverarbeitung", "Satzung"]:
        c.drawString(2 * cm, y, f"[X]  {text}")
        y -= 0.65 * cm

    c.save()

    pdf_bytes = buf.getvalue()
    fname = f"antrag_{user.first_name}_{user.last_name}_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    verwaltung, _ = Folder.objects.get_or_create(name="Verwaltung", parent=None)
    folder, _ = Folder.objects.get_or_create(name="Mitglieder", parent=verwaltung)
    FilerFile.objects.create(
        file=ContentFile(pdf_bytes, name=fname),
        original_filename=fname,
        name=fname,
        owner=user,
        folder=folder,
        mime_type="application/pdf",
    )
    return pdf_bytes, fname


def home(request):
    termine = (
        Termin.objects.filter(datum__gte=tz_now())
        .order_by("datum")
        .select_related("ort")[:10]
    )
    return render(request, "index.html", {
        "termine": termine,
        "homepage_ueber_uns": get_config("HOMEPAGE_UEBER_UNS", ""),
        "homepage_aufnahme": get_config("HOMEPAGE_AUFNAHME", ""),
        "vereinsadresse": get_config("VEREINSADRESSE", ""),
        "kontakt_email": get_config("DEFAULT_FROM_EMAIL", ""),
    })


def datenschutz(request):
    vorstand = (
        User.objects.filter(groups__name="Vorstand", is_active=True)
        .order_by("last_name", "first_name")
    )
    return render(request, "datenschutz.html", {
        "vorstand": vorstand,
        "kontakt_email": get_from_email(),
        "vereinsadresse": get_config("VEREINSADRESSE"),
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
                send_branded_mail(
                    subject,
                    user.email,
                    "emails/password_reset.html",
                    {"user": user, "link": link},
                    text_body=format_config_mail("MAIL_NEUES_PASSWORT", user, link=link),
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
        form.user._audit_user = form.user
        form.user._audit_password_changed = True
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
            user.date_joined = None
            user._audit_user = user
            user._audit_application = True
            user.save()
            form.save_m2m()

            pdf_attachment = None
            try:
                pdf_bytes, pdf_fname = _save_antrag_pdf(user, email)
                pdf_attachment = [(pdf_fname, pdf_bytes, "application/pdf")]
            except Exception:
                logger.exception("Antrag-PDF konnte nicht erstellt werden fuer %s", user.username)

            send_branded_mail(
                f"Dein Mitgliedsantrag bei {get_vereinsname()}",
                email,
                "emails/mitglied_beitritt_success.html",
                {"user": user},
                attachments=pdf_attachment,
                text_body=format_config_mail("MAIL_ANTRAG", user),
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
                    text_body=format_config_mail("MAIL_ANTRAG_ADMIN", user, link=link),
                )
            return render(request, "mitglied_beitritt_success.html", {"user": user})
    else:
        form = MitgliedBeitrittForm()

    return render(request, "mitglied_beitritt.html", {"form": form, "email": email})


# ---------------------------------------------------------------------------
# Mitglieds-Bestätigung (Daten + Datenschutz / Satzung / Beitrag)
# ---------------------------------------------------------------------------

BESTAETIGUNG_MAX_AGE = 30 * 24 * 3600  # 30 Tage
_bestaetigung_signer = TimestampSigner(salt="intern.mitglied_bestaetigung")


def _make_bestaetigung_token(user_pk):
    return _bestaetigung_signer.sign(str(user_pk))


def _read_bestaetigung_token(token):
    try:
        return int(_bestaetigung_signer.unsign(token, max_age=BESTAETIGUNG_MAX_AGE))
    except (BadSignature, SignatureExpired, ValueError):
        return None


def make_bestaetigung_url(user, base_url):
    """Gibt den signierten Bestätigungs-Link für *user* zurück, ohne Mail zu senden."""
    token = _make_bestaetigung_token(user.pk)
    return f"{base_url.rstrip('/')}/intern/bestaetigung/{token}/"


def _get_bestaetigung_text(user, link):
    try:
        return format_config_mail("MAIL_BESTAETIGUNG", user, link=link)
    except Exception:
        logger.warning("MAIL_BESTAETIGUNG nicht konfiguriert oder fehlerhaft")
        return None


def _save_bestaetigung_pdf(user):
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    _, h = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, h - 2 * cm, f"Datenbestätigung - {get_vereinsname()}")
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, h - 2.8 * cm, f"Bestätigt am: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

    felder = [
        ("Vorname",      user.first_name),
        ("Nachname",     user.last_name),
        ("Benutzername", user.username),
        ("E-Mail",       user.email or ""),
        ("Geburtsdatum", str(user.geburtstag) if user.geburtstag else ""),
        ("Stimmlage",    user.stimme),
        ("Strasse",      user.strasse or ""),
        ("PLZ / Ort",    f"{user.plz or ''} {user.ort or ''}".strip()),
        ("Telefon",      user.telefon or ""),
        ("Mobil",        user.telefon_mobil or ""),
    ]

    y = h - 4 * cm
    for label, wert in felder:
        if not wert:
            continue
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2 * cm, y, f"{label}:")
        c.setFont("Helvetica", 10)
        c.drawString(6 * cm, y, wert)
        y -= 0.65 * cm

    y -= 0.4 * cm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, y, "Bestätigungen (alle bestätigt):")
    y -= 0.65 * cm
    c.setFont("Helvetica", 10)
    for text in [
        "Daten korrekt und aktuell",
        "Datenschutzerklaerung",
        "Satzung",
    ]:
        c.drawString(2 * cm, y, f"[X]  {text}")
        y -= 0.65 * cm

    c.save()

    pdf_bytes = buf.getvalue()
    fname = f"bestaetigung_{user.first_name}_{user.last_name}_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    verwaltung, _ = Folder.objects.get_or_create(name="Verwaltung", parent=None)
    folder, _ = Folder.objects.get_or_create(name="Mitglieder", parent=verwaltung)
    FilerFile.objects.create(
        file=ContentFile(pdf_bytes, name=fname),
        original_filename=fname,
        name=fname,
        owner=user,
        folder=folder,
        mime_type="application/pdf",
    )
    return pdf_bytes, fname


def send_bestaetigung_mail(user, base_url):
    """Schickt die Bestätigungs-Aufforderungs-Mail.

    Wird vom Management-Command ``send_reconfirmation`` aufgerufen.
    ``base_url`` muss Schema + Host enthalten, z. B. ``https://portal.example.com``.
    """
    token = _make_bestaetigung_token(user.pk)
    link = f"{base_url.rstrip('/')}/intern/bestaetigung/{token}/"
    text_body = _get_bestaetigung_text(user, link)
    send_branded_mail(
        "Bitte bestätige Deine Mitgliedsdaten",
        user.email,
        "emails/mitglied_bestaetigung_aufforderung.html",
        {"user": user, "link": link},
        text_body=text_body,
    )


def mitglied_bestaetigung(request, token):
    """Öffentliches Bestätigungsformular hinter einem signierten Link.

    Zeigt die aktuellen Mitgliedsdaten und vier Bestätigungs-Checkboxen.
    Bei Absenden wird ein PDF gespeichert und per Mail als Quittung versandt.
    Kein Login erforderlich, kein Vorstand-Notify.
    """
    user_pk = _read_bestaetigung_token(token)
    if user_pk is None:
        return render(request, "mitglied_bestaetigung_invalid.html", status=400)

    try:
        user = User.objects.get(pk=user_pk, is_active=True)
    except User.DoesNotExist:
        return render(request, "mitglied_bestaetigung_invalid.html", status=400)

    if request.method == "POST":
        form = MitgliedBestaetigungForm(request.POST)
        if form.is_valid():
            pdf_attachment = None
            try:
                pdf_bytes, pdf_fname = _save_bestaetigung_pdf(user)
                pdf_attachment = [(pdf_fname, pdf_bytes, "application/pdf")]
            except Exception:
                logger.exception(
                    "Bestätigung-PDF konnte nicht erstellt werden fuer %s", user.username
                )

            send_branded_mail(
                f"Deine Datenbestätigung – {get_vereinsname()}",
                user.email,
                "emails/mitglied_bestaetigung_bestaetigt.html",
                {"user": user},
                attachments=pdf_attachment,
                text_body=format_config_mail("MAIL_BESTAETIGUNG_BESTAETIGT", user),
            )
            return render(request, "mitglied_bestaetigung_success.html", {"user": user})
    else:
        form = MitgliedBestaetigungForm()

    return render(request, "mitglied_bestaetigung.html", {"form": form, "user": user})


def custom_400(request, exception):
    return render(request, "400.html", status=400)


def custom_403(request, exception):
    return render(request, "403.html", status=403)


def custom_404(request, exception):
    return render(request, "404.html", status=404)


def custom_500(request):
    return render(request, "500.html", status=500)