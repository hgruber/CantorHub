from django import forms
from django.db import models
from filer.fields.file import FilerFileField
from filer.fields.image import AdminImageWidget

from .models import User


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


class TerminForm(forms.Form):
    kurz = forms.CharField(max_length=64, required=True)
    datum = forms.DateTimeField()
    datum_bis = forms.DateTimeInput()
    lang = forms.TextInput()


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
