import re
from datetime import datetime

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.crypto import get_random_string
from django.utils.safestring import mark_safe
from django.db import models
from filer.fields.file import FilerFileField
from filer.fields.image import AdminImageWidget

from .models import (
    ADDRESS_TRIGGER_FIELDS,
    Forum,
    Konfiguration,
    Lied,
    Ort,
    PRIVACY_FIELDS,
    Termin,
    User,
)


class TriStateToggle(forms.Select):
    """Three-position sliding toggle for boolean filter fields.

    Renders a hidden <select> (unknown/true/false) plus a pill-shaped
    sliding switch: red ✗ (exclude) | grey · (any) | green ✓ (include).
    """

    def __init__(self, attrs=None):
        choices = [("unknown", "Egal"), ("true", "Ja"), ("false", "Nein")]
        super().__init__(attrs, choices)

    _OFFSETS = {"false": "0px", "unknown": "14px", "true": "28px"}

    def render(self, name, value, attrs=None, renderer=None):
        if value is True or value == "true" or value == "2":
            str_value, current = "true", "true"
        elif value is False or value == "false" or value == "3":
            str_value, current = "false", "false"
        else:
            str_value, current = "unknown", "unknown"
        select_html = super().render(
            name, str_value,
            attrs={"class": "tri-toggle-select", **(attrs or {})},
            renderer=renderer,
        )
        # Inline transform on the thumb prevents a flash before JS runs.
        thumb_style = f'style="transform:translateX({self._OFFSETS[current]})"'
        toggle_html = (
            f'<div class="tri-toggle" data-value="{current}">'
            f'<span class="tri-toggle-thumb" {thumb_style}></span>'
            f'<button type="button" class="tri-toggle-seg{" selected" if current == "false" else ""}" data-val="false" title="Ausschließen">&#x2717;</button>'
            f'<button type="button" class="tri-toggle-seg{" selected" if current == "unknown" else ""}" data-val="unknown" title="Egal"></button>'
            f'<button type="button" class="tri-toggle-seg{" selected" if current == "true" else ""}" data-val="true" title="Einschließen">&#x2713;</button>'
            f'</div>'
        )
        return mark_safe(f'<div class="tri-toggle-wrap">{select_html}{toggle_html}</div>')

    class Media:
        js = ("intern/js/tri-toggle.js",)


class RegisterForm(forms.Form):
    first_name = forms.CharField(max_length=32, label="Vorname", required=False)
    last_name = forms.CharField(max_length=32, label="Nachname", required=False)
    username = forms.CharField(
        max_length=100, label="gewünschter Benutzername", required=False
    )
    email = forms.EmailField(
        max_length=100, label="Deine E-Mail Adresse", required=False
    )

    def clean(self):
        cleaned_data = super().clean()
        first_name = cleaned_data.get("first_name")
        last_name = cleaned_data.get("last_name")
        username = cleaned_data.get("username")
        email = cleaned_data.get("email")

        if not (username or email or (first_name and last_name)):
            raise forms.ValidationError(
                "Entweder muss ein Benutzername oder eine E-Mail-Adresse oder sowohl Vorname als auch Nachname angegeben werden."
            )
        return cleaned_data


class MitgliedInviteForm(forms.Form):
    """Off-Canvas-Schritt 1: nur eine E-Mail, an die eine Einladung geht."""

    email = forms.EmailField(
        label="E-Mail-Adresse",
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "name@beispiel.de"}
        ),
    )


# Erlaubte Zeichen für neue Benutzernamen (3–30: Buchstaben, Ziffern, . _ -).
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")


class MitgliedBeitrittForm(forms.ModelForm):
    """Öffentliches Beitritts-Formular. Die E-Mail kommt aus dem Einladungs-Token
    und ist daher kein Formularfeld."""

    password1 = forms.CharField(
        label="Passwort",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )
    password2 = forms.CharField(
        label="Passwort wiederholen",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    zustimmung_datenschutz = forms.BooleanField(
        required=True,
        label=mark_safe(
            'Ich habe die <a href="/datenschutz/" target="_blank" rel="noopener">'
            "Datenschutzerklärung</a> gelesen und stimme ihr zu."
        ),
    )
    zustimmung_datenverarbeitung = forms.BooleanField(
        required=True,
        label="Ich willige in die Verarbeitung meiner angegebenen Daten zu "
        "Vereinszwecken ein.",
    )
    anerkennung_satzung = forms.BooleanField(
        required=True,
        label=mark_safe(
            'Ich erkenne die <a href="#" target="_blank" rel="noopener">'
            "Satzung</a> des Vereins an."
        ),
    )
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from intern.app_settings import get_document_url
        satzung_url = get_document_url("SATZUNG_FILE_ID")
        self.fields["anerkennung_satzung"].label = mark_safe(
            f'Ich erkenne die <a href="{satzung_url}" target="_blank" rel="noopener">'
            "Satzung</a> des Vereins an."
        )

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "username",
            "stimme",
            "geburtstag",
            "strasse",
            "plz",
            "ort",
            "telefon",
            "telefon_mobil",
            "telefon_job",
            "telefon_job_mobil",
            "fax",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "stimme": forms.Select(attrs={"class": "form-control"}),
            "geburtstag": forms.DateInput(
                format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}
            ),
            "strasse": forms.TextInput(attrs={"class": "form-control"}),
            "plz": forms.TextInput(attrs={"class": "form-control"}),
            "ort": forms.TextInput(attrs={"class": "form-control"}),
            "telefon": forms.TextInput(attrs={"class": "form-control"}),
            "telefon_mobil": forms.TextInput(attrs={"class": "form-control"}),
            "telefon_job": forms.TextInput(attrs={"class": "form-control"}),
            "telefon_job_mobil": forms.TextInput(attrs={"class": "form-control"}),
            "fax": forms.TextInput(attrs={"class": "form-control"}),
        }

    # Pflichtfelder, die im Modell eigentlich optional (blank/null) sind.
    REQUIRED = ["geburtstag", "strasse", "plz", "ort"]
    PHONE_FIELDS = ["telefon", "telefon_mobil", "telefon_job", "telefon_job_mobil"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.REQUIRED:
            self.fields[name].required = True
        # stimme nie als „None" zur Auswahl anbieten.
        self.fields["stimme"].required = True
        self.fields["stimme"].choices = [
            (k, v) for k, v in User.STIMMEN if k != "N"
        ]

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not USERNAME_RE.match(username):
            raise ValidationError(
                "Der Benutzername darf nur Buchstaben, Ziffern sowie . _ - "
                "enthalten und muss 3–30 Zeichen lang sein."
            )
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Dieser Benutzername ist bereits vergeben.")
        return username

    def clean(self):
        cleaned = super().clean()

        if not any(cleaned.get(f) for f in self.PHONE_FIELDS):
            self.add_error(
                "telefon", "Bitte gib mindestens eine Telefonnummer an."
            )

        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "Die Passwörter stimmen nicht überein.")
            else:
                try:
                    validate_password(p1)
                except ValidationError as exc:
                    self.add_error("password1", exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = False
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            self.save_m2m()
        return user


class MitgliedBestaetigungForm(forms.Form):
    bestaetigung_daten = forms.BooleanField(
        required=True,
        label="Meine gespeicherten Daten sind korrekt und aktuell.",
    )
    zustimmung_datenschutz = forms.BooleanField(
        required=True,
        label=mark_safe(
            'Ich habe die <a href="/datenschutz/" target="_blank" rel="noopener">'
            "Datenschutzerklärung</a> gelesen und stimme ihr zu."
        ),
    )
    anerkennung_satzung = forms.BooleanField(
        required=True,
        label=mark_safe(
            'Ich erkenne die <a href="#" target="_blank" rel="noopener">'
            "Satzung</a> des Vereins an."
        ),
    )
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from intern.app_settings import get_document_url
        satzung_url = get_document_url("SATZUNG_FILE_ID")
        self.fields["anerkennung_satzung"].label = mark_safe(
            f'Ich erkenne die <a href="{satzung_url}" target="_blank" rel="noopener">'
            "Satzung</a> des Vereins an."
        )


class TerminForm(forms.ModelForm):
    uhrzeit = forms.TimeField(
        required=False,
        label="Uhrzeit",
        widget=forms.TimeInput(
            format="%H:%M",
            attrs={"class": "form-control", "type": "time"},
        ),
    )

    class Meta:
        model = Termin
        fields = ["kurz", "datum", "uhrzeit", "datum_bis", "lang", "ort", "anwesenheit", "repertoire"]
        widgets = {
            "kurz": forms.TextInput(attrs={"class": "form-control"}),
            "datum": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "form-control", "type": "date"},
            ),
            "datum_bis": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"class": "form-control", "type": "datetime-local"},
            ),
            "lang": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "ort": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.datum:
            self.initial["uhrzeit"] = self.instance.datum.strftime("%H:%M")

    def clean(self):
        cleaned = super().clean()
        datum = cleaned.get("datum")
        uhrzeit = cleaned.get("uhrzeit")
        if datum and uhrzeit:
            cleaned["datum"] = datetime.combine(datum, uhrzeit)
        elif datum:
            cleaned["datum"] = datetime.combine(datum, datetime.min.time())
        return cleaned


class LiedEditForm(forms.ModelForm):
    solist = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("last_name", "first_name"),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-control", "size": "8"}),
    )
    dirigent = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("last_name", "first_name"),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-control", "size": "8"}),
    )

    class Meta:
        model = Lied
        fields = [
            "titel", "aktiv", "tempo", "beats", "hymne", "acapella", "weihnacht",
            "original", "aufnahme", "pdf", "noten", "komponist", "bearbeiter",
            "solist", "dirigent",
        ]
        widgets = {
            "titel": forms.TextInput(attrs={"class": "form-control"}),
            "aktiv": forms.CheckboxInput(),
            "tempo": forms.Select(attrs={"class": "form-control"}),
            "beats": forms.NumberInput(attrs={"class": "form-control"}),
            "hymne": forms.CheckboxInput(),
            "acapella": forms.CheckboxInput(),
            "weihnacht": forms.CheckboxInput(),
            "original": AdminImageWidget,
            "aufnahme": AdminImageWidget,
            "pdf": AdminImageWidget,
            "noten": AdminImageWidget,
            "komponist": forms.TextInput(attrs={"class": "form-control"}),
            "bearbeiter": forms.TextInput(attrs={"class": "form-control"}),
        }


class ForumEditForm(forms.ModelForm):
    bild = FilerFileField(null=True, blank=True, on_delete=models.SET_NULL, related_name="forum_bild")

    class Meta:
        model = Forum
        fields = ["thema", "bild", "xmpp_muc_jid"]
        widgets = {
            "thema": forms.TextInput(attrs={"class": "form-control"}),
            "bild": AdminImageWidget,
            "xmpp_muc_jid": forms.TextInput(attrs={"class": "form-control", "placeholder": "forum-262@conference.example.org"}),
        }


class UserEditForm(forms.ModelForm):
    avatar = FilerFileField(
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="avatar",
    )

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "avatar",
            "username",
            "email",
            "stimme",
            "geburtstag",
            "strasse",
            "plz",
            "ort",
            "telefon",
            "telefon_job",
            "telefon_mobil",
            "telefon_job_mobil",
            "fax",
            "xmpp",
            "text",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "avatar": AdminImageWidget,
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "stimme": forms.Select(attrs={"class": "form-control"}),
            "geburtstag": forms.DateInput(
                format="%Y-%m-%d", attrs={"class": "form-control", "type": "date"}
            ),
            "strasse": forms.TextInput(attrs={"class": "form-control"}),
            "plz": forms.TextInput(attrs={"class": "form-control"}),
            "ort": forms.TextInput(attrs={"class": "form-control"}),
            "telefon": forms.TextInput(attrs={"class": "form-control"}),
            "telefon_job": forms.TextInput(attrs={"class": "form-control"}),
            "telefon_mobil": forms.TextInput(attrs={"class": "form-control"}),
            "telefon_job_mobil": forms.TextInput(attrs={"class": "form-control"}),
            "fax": forms.TextInput(attrs={"class": "form-control"}),
            "xmpp": forms.TextInput(attrs={"class": "form-control"}),
            "text": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
        }

    def __init__(self, *args, with_privacy=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._with_privacy = with_privacy
        if not with_privacy:
            return
        current = set((self.instance.private_fields or []) if self.instance else [])
        for f in PRIVACY_FIELDS:
            self.fields[f"priv_{f}"] = forms.BooleanField(
                required=False,
                initial=f in current,
                label="verbergen",
            )

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self._with_privacy:
            hidden = [f for f in PRIVACY_FIELDS if self.cleaned_data.get(f"priv_{f}")]
            instance.private_fields = hidden
            if set(hidden) & ADDRESS_TRIGGER_FIELDS:
                instance.breite = None
                instance.laenge = None
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class OrtForm(forms.ModelForm):
    class Meta:
        model = Ort
        fields = ["name", "beschreibung", "strasse", "plz", "ort", "breite", "laenge"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "beschreibung": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "strasse": forms.TextInput(attrs={"class": "form-control"}),
            "plz": forms.TextInput(attrs={"class": "form-control"}),
            "ort": forms.TextInput(attrs={"class": "form-control"}),
            "breite": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "laenge": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
        }


class MitgliedAddForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        required=False,
        label="Passwort",
        help_text="Leer lassen für automatisches Passwort.",
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "stimme"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "stimme": forms.Select(attrs={"class": "form-control"}),
        }

    def clean_password(self):
        return self.cleaned_data.get("password")

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        else:
            user.set_password(get_random_string(10))
        if commit:
            user.save()
        return user


class KonfigurationForm(forms.ModelForm):
    class Meta:
        model = Konfiguration
        fields = ["key", "value", "description"]
        widgets = {
            "key": forms.TextInput(attrs={"class": "inline-input"}),
            "value": forms.Textarea(attrs={"class": "inline-input", "rows": 1}),
            "description": forms.Textarea(attrs={"class": "inline-input", "rows": 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["key"].widget.attrs["readonly"] = True
