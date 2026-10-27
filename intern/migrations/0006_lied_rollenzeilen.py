"""Die vier Dateifelder am Lied fallen — die Rollenzeile ist die einzige Quelle.

Vor dem Entfernen bekommt jedes Feld, das noch auf eine Datei zeigt und keine
Rollenzeile hat, eine solche. Das betrifft Dateien aus dem Fenster zwischen
Bestandsumzug und Umschaltung (etwa entpackte Archive), die nur über den alten
FK zugeordnet wurden. Erst danach fallen die Spalten; der Rückweg führt über
diese Rollenzeilen zurück in die Felder.
"""

from django.db import migrations

# Alter Feldname → Rollenschlüssel (siehe intern/liedrollen.py).
FELDER = (
    ("original", "original"),
    ("aufnahme", "aufnahme"),
    ("pdf", "notenblatt"),
    ("noten", "notensatz"),
)


def rollenzeilen_nachtragen(apps, schema_editor):
    Lied = apps.get_model("intern", "Lied")
    LiedDatei = apps.get_model("intern", "LiedDatei")
    for feld, rolle in FELDER:
        zeilen = (
            Lied.objects.exclude(**{f"{feld}_id": None})
            .values_list("pk", f"{feld}_id")
        )
        for lied_id, datei_id in zeilen:
            LiedDatei.objects.get_or_create(
                lied_id=lied_id, rolle=rolle, defaults={"datei_id": datei_id}
            )


def felder_zurueckschreiben(apps, schema_editor):
    Lied = apps.get_model("intern", "Lied")
    LiedDatei = apps.get_model("intern", "LiedDatei")
    for feld, rolle in FELDER:
        for lied_id, datei_id in LiedDatei.objects.filter(rolle=rolle).values_list(
            "lied_id", "datei_id"
        ):
            Lied.objects.filter(pk=lied_id).update(**{f"{feld}_id": datei_id})


class Migration(migrations.Migration):

    dependencies = [
        ("intern", "0005_lied_rollen"),
    ]

    operations = [
        migrations.RunPython(rollenzeilen_nachtragen, felder_zurueckschreiben),
        migrations.RemoveField(model_name="lied", name="original"),
        migrations.RemoveField(model_name="lied", name="aufnahme"),
        migrations.RemoveField(model_name="lied", name="pdf"),
        migrations.RemoveField(model_name="lied", name="noten"),
    ]
