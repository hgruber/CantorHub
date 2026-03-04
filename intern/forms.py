from django import forms


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
