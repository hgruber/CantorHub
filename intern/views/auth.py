import logging
import threading
from datetime import datetime
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
from intern import ejabberd
from intern.app_settings import (
    get_config,
    get_config_int,
    get_from_email,
    get_vereinsname,
    is_ejabberd_configured,
)
from intern.pdf import (
    draw_checkbox,
    draw_field,
    draw_section,
    draw_signature,
    new_letterhead_pdf,
)
from intern.mail import send_config_mail

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


def _save_antrag_pdf(user, email, einwilligung_fotos=False, foerdermitglied=False):
    buf, c, y = new_letterhead_pdf(
        title="Mitgliedsantrag",
        subtitle=f"Eingereicht am: {datetime.now().strftime('%d.%m.%Y um %H:%M Uhr')}",
        vereinsname=get_vereinsname(),
        vereinsadresse=get_config("VEREINSADRESSE", ""),
    )

    felder = [
        ("Vorname:",      user.first_name),
        ("Nachname:",     user.last_name),
        ("Benutzername:", user.username),
        ("E-Mail:",       email),
        ("Geburtsdatum:", str(user.geburtstag) if user.geburtstag else ""),
        ("Stimmlage:",    user.stimme),
        ("Straße:",       user.strasse or ""),
        ("PLZ / Ort:",    f"{user.plz or ''} {user.ort or ''}".strip()),
        ("Telefon:",      user.telefon or ""),
        ("Mobil:",        user.telefon_mobil or ""),
    ]

    y = draw_section(c, y, "Persönliche Daten")
    for label, wert in felder:
        if wert:
            y = draw_field(c, y, label, wert)

    y = draw_section(c, y, "Einwilligungen (Pflichtfelder alle bestätigt)")
    y = draw_checkbox(c, y, "Angaben sind wahrheitsgemäß und vollständig")
    y = draw_checkbox(c, y, "Datenschutzerklärung gelesen und akzeptiert")
    y = draw_checkbox(c, y, "Datenverarbeitung durch den Verein akzeptiert")
    y = draw_checkbox(c, y, "Satzung gelesen und akzeptiert")
    y = draw_checkbox(c, y, "Beitragsordnung zur Kenntnis genommen und anerkannt")
    y = draw_checkbox(c, y, "Einwilligung zur Veröffentlichung von Fotos bei Auftritten",
                     checked=einwilligung_fotos)

    y = draw_section(c, y, "Fördermitgliedschaft")
    y = draw_checkbox(c, y, "Ich möchte förderndes Mitglied werden", checked=foerdermitglied)

    draw_signature(c, y, f"{user.first_name} {user.last_name}")

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
        Termin.objects.filter(datum__gte=tz_now(), repertoire=True)
        .order_by("datum")
        .select_related("ort")[:10]
    )
    ueber_uns = get_config("HOMEPAGE_UEBER_UNS", "")
    # erster Satz als Anrisstext im Hero-Bereich
    kopf, punkt, _ = ueber_uns.partition(".")
    return render(request, "index.html", {
        "termine": termine,
        "homepage_intro": (kopf + punkt).strip(),
        "homepage_ueber_uns": ueber_uns,
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
        "hosting_anbieter_name": get_config(
            "HOSTING_ANBIETER_NAME", "Hetzner Online GmbH"
        ),
        "hosting_anbieter_anschrift": get_config(
            "HOSTING_ANBIETER_ANSCHRIFT",
            "Industriestr. 25, 91710 Gunzenhausen, Deutschland",
        ),
        "dsb_name": get_config(
            "DSB_NAME",
            "Der Hessische Beauftragte für Datenschutz und Informationsfreiheit (HBDI)",
        ),
        "dsb_anschrift": get_config(
            "DSB_ANSCHRIFT", "Gustav-Stresemann-Ring 1, 65189 Wiesbaden"
        ),
        "dsb_url": get_config("DSB_URL", "https://www.datenschutz.hessen.de"),
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
    """Client-IP am Ende der Proxy-Kette (haproxy → nginx → gunicorn).

    Genommen wird der **letzte** Eintrag in X-Forwarded-For, nicht der erste:
    was ein Client selbst mitschickt, steht immer weiter vorn und kann so nicht
    durchschlagen.  Voraussetzung ist, dass nginx per ``set_real_ip_from``
    (nginx.conf) die echte Client-IP aus dem haproxy-Header übernimmt und als
    einzigen Eintrag weiterreicht — ohne diese Konfiguration liefert die
    Funktion die Adresse des vorgelagerten Proxys.  Siehe docs/architecture.md,
    Abschnitt „What Django assumes about the proxy".
    """
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
                send_config_mail(
                    subject,
                    user.email,
                    "MAIL_NEUES_PASSWORT",
                    user=user,
                    link=link,
                    context={"mail_title": subject},
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

    Synchronisiert das neue Passwort anschließend zu ejabberd.
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

def _invite_max_age():
    """Gültigkeit des Einladungs-Tokens in Sekunden, aus der Konfiguration."""
    return get_config_int("MITGLIED_EINLADUNG_TAGE", 7) * 24 * 3600


_invite_signer = TimestampSigner(salt="intern.mitglied_invite")


def make_invite_token(email):
    """Signierter Token, der die eingeladene E-Mail trägt."""
    return _invite_signer.sign(email)


def _read_invite_token(token):
    """E-Mail aus einem gültigen Token, sonst None (ungültig/abgelaufen)."""
    try:
        return _invite_signer.unsign(token, max_age=_invite_max_age())
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

            foerdermitglied = form.cleaned_data.get("foerdermitglied", False)
            if foerdermitglied:
                from django.contrib.auth.models import Group as AuthGroup
                try:
                    user.groups.add(AuthGroup.objects.get(name="Fördermitglied"))
                except AuthGroup.DoesNotExist:
                    logger.warning("Gruppe 'Fördermitglied' nicht gefunden")

            minderjaehrig = False
            if user.geburtstag:
                from datetime import date as _date
                today = _date.today()
                age = today.year - user.geburtstag.year
                if (today.month, today.day) < (user.geburtstag.month, user.geburtstag.day):
                    age -= 1
                minderjaehrig = age < 18

            pdf_attachment = None
            try:
                pdf_bytes, pdf_fname = _save_antrag_pdf(
                    user, email,
                    einwilligung_fotos=form.cleaned_data.get("einwilligung_fotos", False),
                    foerdermitglied=foerdermitglied,
                )
                pdf_attachment = [(pdf_fname, pdf_bytes, "application/pdf")]
            except Exception:
                logger.exception("Antrag-PDF konnte nicht erstellt werden fuer %s", user.username)

            send_config_mail(
                f"Dein Mitgliedsantrag bei {get_vereinsname()}",
                email,
                "MAIL_ANTRAG",
                user=user,
                attachments=pdf_attachment,
            )

            antrag_email = get_config("ANTRAG_EMAIL", "").strip()
            empfaenger = [antrag_email] if antrag_email else [u.email for u in _member_managers() if u.email]
            if empfaenger:
                link = request.build_absolute_uri(
                    reverse("mitglied_view", args=[user.id])
                )
                hinweise = []
                if minderjaehrig:
                    hinweise.append("MAIL_ANTRAG_ADMIN_MINDERJAEHRIG")
                if foerdermitglied:
                    hinweise.append("MAIL_ANTRAG_ADMIN_FOERDER")
                send_config_mail(
                    "Neuer Mitgliedsantrag",
                    empfaenger,
                    "MAIL_ANTRAG_ADMIN",
                    user=user,
                    link=link,
                    extra_keys=hinweise,
                )
            return render(request, "mitglied_beitritt_success.html", {"user": user})
    else:
        form = MitgliedBeitrittForm()

    return render(request, "mitglied_beitritt.html", {"form": form, "email": email})


# ---------------------------------------------------------------------------
# Mitglieds-Bestätigung (Daten + Datenschutz / Satzung / Beitrag)
# ---------------------------------------------------------------------------

def _bestaetigung_max_age():
    """Gültigkeit des Bestätigungs-Tokens in Sekunden, aus der Konfiguration."""
    return get_config_int("MITGLIED_BESTAETIGUNG_TAGE", 30) * 24 * 3600


_bestaetigung_signer = TimestampSigner(salt="intern.mitglied_bestaetigung")


def _make_bestaetigung_token(user_pk):
    return _bestaetigung_signer.sign(str(user_pk))


def _read_bestaetigung_token(token):
    try:
        return int(_bestaetigung_signer.unsign(token, max_age=_bestaetigung_max_age()))
    except (BadSignature, SignatureExpired, ValueError):
        return None


def make_bestaetigung_url(user, base_url):
    """Gibt den signierten Bestätigungs-Link für *user* zurück, ohne Mail zu senden."""
    token = _make_bestaetigung_token(user.pk)
    return f"{base_url.rstrip('/')}/intern/bestaetigung/{token}/"


def _save_bestaetigung_pdf(user):
    buf, c, y = new_letterhead_pdf(
        title="Datenbestätigung",
        subtitle=f"Bestätigt am: {datetime.now().strftime('%d.%m.%Y um %H:%M Uhr')}",
        vereinsname=get_vereinsname(),
        vereinsadresse=get_config("VEREINSADRESSE", ""),
    )

    felder = [
        ("Vorname:",      user.first_name),
        ("Nachname:",     user.last_name),
        ("Benutzername:", user.username),
        ("E-Mail:",       user.email or ""),
        ("Geburtsdatum:", str(user.geburtstag) if user.geburtstag else ""),
        ("Stimmlage:",    user.stimme),
        ("Straße:",       user.strasse or ""),
        ("PLZ / Ort:",    f"{user.plz or ''} {user.ort or ''}".strip()),
        ("Telefon:",      user.telefon or ""),
        ("Mobil:",        user.telefon_mobil or ""),
    ]

    y = draw_section(c, y, "Gespeicherte Mitgliedsdaten")
    for label, wert in felder:
        if wert:
            y = draw_field(c, y, label, wert)

    y = draw_section(c, y, "Bestätigungen (alle bestätigt)")
    y = draw_checkbox(c, y, "Daten korrekt und aktuell")
    y = draw_checkbox(c, y, "Datenschutzerklärung gelesen und akzeptiert")
    y = draw_checkbox(c, y, "Satzung gelesen und akzeptiert")
    draw_signature(c, y, f"{user.first_name} {user.last_name}")

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
    send_config_mail(
        "Bitte bestätige Deine Mitgliedsdaten",
        user.email,
        "MAIL_BESTAETIGUNG",
        user=user,
        link=link,
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

            send_config_mail(
                f"Deine Datenbestätigung – {get_vereinsname()}",
                user.email,
                "MAIL_BESTAETIGUNG_BESTAETIGT",
                user=user,
                attachments=pdf_attachment,
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