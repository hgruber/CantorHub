from django import forms
from django.db import models
from filer.fields.file import FilerFileField
from filer.fields.image import AdminImageWidget

from .models import Forum, Lied, Ort, Termin, User


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


class TerminForm(forms.ModelForm):
    class Meta:
        model = Termin
        fields = ["kurz", "datum", "datum_bis", "lang", "ort", "anwesenheit", "repertoire"]
        widgets = {
            "kurz": forms.TextInput(attrs={"class": "form-control"}),
            "datum": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"class": "form-control", "type": "datetime-local"},
            ),
            "datum_bis": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"class": "form-control", "type": "datetime-local"},
            ),
            "lang": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "ort": forms.Select(attrs={"class": "form-control"}),
        }


class LiedEditForm(forms.ModelForm):
    class Meta:
        model = Lied
        fields = [
            "titel", "aktiv", "tempo", "beats", "hymne", "acapella", "weihnacht",
            "original", "aufnahme", "pdf", "noten", "komponist", "bearbeiter",
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
        fields = ["thema", "bild"]
        widgets = {
            "thema": forms.TextInput(attrs={"class": "form-control"}),
            "bild": AdminImageWidget,
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
